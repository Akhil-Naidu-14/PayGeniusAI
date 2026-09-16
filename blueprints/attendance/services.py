"""
AttendanceService: Business logic for employee attendance management.

Company working rules:
  - Office Start: 09:00 AM (local)
  - Office End:   05:00 PM / 17:00 (local)
  - Standard Hours: 8.0

All computation results are stored explicitly (stored fields).
All numeric values use Decimal to avoid floating-point rounding errors.
All datetimes are timezone-aware.
"""

import logging
from datetime import date, time, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from contextlib import contextmanager
from sqlalchemy import extract

from extensions import db
from models.attendance import Attendance, AttendanceStatus
from models.employee import Employee

logger = logging.getLogger(__name__)


@contextmanager
def transaction_or_flush(session):
    """
    Runs block inside session.begin() context manager if no transaction is active.
    Otherwise runs it directly and performs a session.flush() at the end to keep
    it within the outer transaction scope.
    Handles scoped_session proxies by resolving the underlying Session.
    """
    # Resolve proxied session if scoped_session
    if hasattr(session, "_proxied"):
        actual_session = session._proxied
    elif callable(session):
        actual_session = session()
    else:
        actual_session = session

    if actual_session.in_transaction():
        yield
        actual_session.flush()
    else:
        with actual_session.begin():
            yield


# ---------------------------------------------------------------------------
# Company constants
# ---------------------------------------------------------------------------
OFFICE_START = time(9, 0)   # 09:00 AM
OFFICE_END   = time(17, 0)  # 05:00 PM
STANDARD_HOURS = Decimal("8.00")


def _now_utc() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _today_local() -> date:
    """Return today's date in local time (server)."""
    return datetime.now(timezone.utc).date()


def _compute_attendance_fields(check_in: datetime, check_out: datetime) -> dict:
    """
    Pure computation function — derives all stored attendance fields.

    Returns a dict with:
        working_hours, overtime_hours, late_minutes, early_leave_minutes
    All values are Decimal / int. No negative values permitted.
    """
    # Working hours
    delta_seconds = (check_out - check_in).total_seconds()
    working_hours = Decimal(str(delta_seconds / 3600)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    # Guard against negative working hours (clock correction edge-case)
    working_hours = max(Decimal("0.00"), working_hours)

    # Overtime hours
    overtime_hours = max(Decimal("0.00"), working_hours - STANDARD_HOURS).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Late minutes: how many minutes after 09:00 did the employee check in?
    office_start_dt = datetime.combine(check_in.date(), OFFICE_START)
    if check_in.tzinfo is not None:
        office_start_dt = office_start_dt.replace(tzinfo=check_in.tzinfo)

    if check_in > office_start_dt:
        late_minutes = int(max(0, (check_in - office_start_dt).total_seconds() / 60))
    else:
        late_minutes = 0

    # Early leave minutes: how many minutes before 17:00 did the employee check out?
    office_end_dt = datetime.combine(check_out.date(), OFFICE_END)
    if check_out.tzinfo is not None:
        office_end_dt = office_end_dt.replace(tzinfo=check_out.tzinfo)

    if check_out < office_end_dt:
        early_leave_minutes = int(max(0, (office_end_dt - check_out).total_seconds() / 60))
    else:
        early_leave_minutes = 0

    return {
        "working_hours":       working_hours,
        "overtime_hours":      overtime_hours,
        "late_minutes":        late_minutes,
        "early_leave_minutes": early_leave_minutes,
    }


class AttendanceService:
    """
    AttendanceService contains all business logic for attendance management.
    Routes delegate all computation and persistence to this class.
    """

    # -----------------------------------------------------------------------
    # Employee self-service: Check-In
    # -----------------------------------------------------------------------
    @staticmethod
    def check_in(employee_id: int) -> tuple[bool, str, Attendance | None]:
        """
        Records a check-in for an employee for today.

        Returns (success, status_code, attendance_record | None).

        Status codes:
            SUCCESS              – check-in created
            NOT_FOUND            – employee not found or inactive
            ALREADY_CHECKED_IN   – record already has a check_in
            RECORD_DELETED       – soft-deleted record exists for today
        """
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return False, "NOT_FOUND", None

        today = _today_local()
        existing = (
            Attendance.query
            .filter_by(employee_id=employee_id, date=today)
            .first()
        )

        if existing:
            if not existing.is_active:
                return False, "RECORD_DELETED", None
            if existing.check_in is not None:
                return False, "ALREADY_CHECKED_IN", None

        try:
            now = _now_utc()
            with transaction_or_flush(db.session):
                if existing:
                    existing.check_in = now
                    existing.status   = AttendanceStatus.PRESENT
                    record = existing
                else:
                    record = Attendance(
                        employee_id=employee_id,
                        date=today,
                        check_in=now,
                        status=AttendanceStatus.PRESENT,
                    )
                    db.session.add(record)

            logger.info(
                "ATTENDANCE_CHECK_IN",
                extra={"employee_id": employee_id, "date": str(today)}
            )
            return True, "SUCCESS", record

        except Exception as e:
            logger.error(
                "ATTENDANCE_CHECK_IN_ERROR",
                extra={"employee_id": employee_id, "error": str(e)}
            )
            return False, "DATABASE_ERROR", None

    # -----------------------------------------------------------------------
    # Employee self-service: Check-Out
    # -----------------------------------------------------------------------
    @staticmethod
    def check_out(employee_id: int) -> tuple[bool, str, Attendance | None]:
        """
        Records a check-out for an employee and calculates computed fields.

        Returns (success, status_code, attendance_record | None).

        Status codes:
            SUCCESS           – check-out recorded and fields computed
            NOT_FOUND         – employee not found or inactive
            NO_CHECK_IN       – no check-in record exists for today
            ALREADY_CHECKED_OUT – check-out already recorded
            RECORD_DELETED    – soft-deleted record exists for today
        """
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return False, "NOT_FOUND", None

        today = _today_local()
        record = (
            Attendance.query
            .filter_by(employee_id=employee_id, date=today)
            .first()
        )

        if not record:
            return False, "NO_CHECK_IN", None
        if not record.is_active:
            return False, "RECORD_DELETED", None
        if record.check_in is None:
            return False, "NO_CHECK_IN", None
        if record.check_out is not None:
            return False, "ALREADY_CHECKED_OUT", None

        try:
            now    = _now_utc()
            fields = _compute_attendance_fields(record.check_in, now)

            with transaction_or_flush(db.session):
                record.check_out           = now
                record.working_hours       = fields["working_hours"]
                record.overtime_hours      = fields["overtime_hours"]
                record.late_minutes        = fields["late_minutes"]
                record.early_leave_minutes = fields["early_leave_minutes"]

            logger.info(
                "ATTENDANCE_CHECK_OUT",
                extra={
                    "employee_id": employee_id,
                    "date": str(today),
                    "working_hours": str(fields["working_hours"]),
                }
            )
            return True, "SUCCESS", record

        except Exception as e:
            logger.error(
                "ATTENDANCE_CHECK_OUT_ERROR",
                extra={"employee_id": employee_id, "error": str(e)}
            )
            return False, "DATABASE_ERROR", None

    # -----------------------------------------------------------------------
    # HR/Admin: Manual attendance mark / override
    # -----------------------------------------------------------------------
    @staticmethod
    def mark_attendance(
        employee_id: int,
        target_date: date,
        status: str,
        check_in: datetime | None = None,
        check_out: datetime | None = None,
    ) -> tuple[bool, str, Attendance | None]:
        """
        HR/Admin manual attendance creation or override.

        Validates status against AttendanceStatus.CHOICES.
        Computes fields when both check_in and check_out are provided.

        Returns (success, status_code, attendance_record | None).

        Status codes:
            SUCCESS      – attendance marked
            NOT_FOUND    – employee not found or inactive
            INVALID_STATUS – status not in CHOICES
            INVALID_TIMES  – check_out before check_in
            DATABASE_ERROR
        """
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return False, "NOT_FOUND", None

        if status not in AttendanceStatus.CHOICES:
            return False, "INVALID_STATUS", None

        if check_in and check_out and check_out <= check_in:
            return False, "INVALID_TIMES", None

        # Compute fields when both timestamps provided
        computed: dict = {}
        if check_in and check_out:
            computed = _compute_attendance_fields(check_in, check_out)

        try:
            existing = (
                Attendance.query
                .filter_by(employee_id=employee_id, date=target_date)
                .first()
            )
            with transaction_or_flush(db.session):
                if existing:
                    existing.status    = status
                    existing.is_active = True  # Restore if soft-deleted
                    existing.check_in  = check_in  if check_in  else existing.check_in
                    existing.check_out = check_out if check_out else existing.check_out
                    if computed:
                        existing.working_hours       = computed["working_hours"]
                        existing.overtime_hours      = computed["overtime_hours"]
                        existing.late_minutes        = computed["late_minutes"]
                        existing.early_leave_minutes = computed["early_leave_minutes"]
                    record = existing
                else:
                    record = Attendance(
                        employee_id=employee_id,
                        date=target_date,
                        status=status,
                        check_in=check_in,
                        check_out=check_out,
                        working_hours=computed.get("working_hours"),
                        overtime_hours=computed.get("overtime_hours", Decimal("0.00")),
                        late_minutes=computed.get("late_minutes", 0),
                        early_leave_minutes=computed.get("early_leave_minutes", 0),
                    )
                    db.session.add(record)

            logger.info(
                "ATTENDANCE_MANUAL_MARK",
                extra={"employee_id": employee_id, "date": str(target_date), "status": status}
            )
            return True, "SUCCESS", record

        except Exception as e:
            logger.error(
                "ATTENDANCE_MANUAL_MARK_ERROR",
                extra={"employee_id": employee_id, "error": str(e)}
            )
            return False, "DATABASE_ERROR", None

    # -----------------------------------------------------------------------
    # View: Single employee's attendance for a date range / day
    # -----------------------------------------------------------------------
    @staticmethod
    def get_employee_attendance(employee_id: int, target_date: date) -> Attendance | None:
        """Returns active attendance record for an employee on a specific date."""
        return (
            Attendance.query
            .filter_by(employee_id=employee_id, date=target_date, is_active=True)
            .first()
        )

    @staticmethod
    def get_employee_attendance_month(
        employee_id: int, month: int, year: int
    ) -> list[Attendance]:
        """Returns all active attendance records for an employee in a given month."""
        return (
            Attendance.query
            .filter(
                Attendance.employee_id == employee_id,
                Attendance.is_active   == True,
                extract("month", Attendance.date) == month,
                extract("year",  Attendance.date) == year,
            )
            .order_by(Attendance.date)
            .all()
        )

    # -----------------------------------------------------------------------
    # HR/Admin: View all attendance for a given date
    # -----------------------------------------------------------------------
    @staticmethod
    def get_all_attendance_for_date(target_date: date) -> list[Attendance]:
        """Returns all active attendance records for all employees on a specific date."""
        return (
            Attendance.query
            .filter_by(date=target_date, is_active=True)
            .order_by(Attendance.employee_id)
            .all()
        )

    # -----------------------------------------------------------------------
    # Monthly Summary
    # -----------------------------------------------------------------------
    @staticmethod
    def get_monthly_summary(employee_id: int, month: int, year: int) -> dict:
        """
        Calculates a monthly attendance summary for an employee.

        Excludes soft-deleted records (is_active=False).

        Returns:
            {
                total_working_hours:       Decimal,
                total_overtime_hours:      Decimal,
                total_late_minutes:        int,
                total_early_leave_minutes: int,
                total_present_days:        int,
                month:                     int,
                year:                      int,
                employee_id:               int,
            }
        """
        records = AttendanceService.get_employee_attendance_month(
            employee_id, month, year
        )

        total_working_hours       = Decimal("0.00")
        total_overtime_hours      = Decimal("0.00")
        total_late_minutes        = 0
        total_early_leave_minutes = 0
        total_present_days        = 0

        for r in records:
            if r.working_hours is not None:
                total_working_hours += Decimal(str(r.working_hours))
            if r.overtime_hours is not None:
                total_overtime_hours += Decimal(str(r.overtime_hours))
            if r.late_minutes is not None:
                total_late_minutes += r.late_minutes
            if r.early_leave_minutes is not None:
                total_early_leave_minutes += r.early_leave_minutes
            if r.status == AttendanceStatus.PRESENT:
                total_present_days += 1

        return {
            "employee_id":               employee_id,
            "month":                     month,
            "year":                      year,
            "total_working_hours":       total_working_hours.quantize(Decimal("0.01")),
            "total_overtime_hours":      total_overtime_hours.quantize(Decimal("0.01")),
            "total_late_minutes":        total_late_minutes,
            "total_early_leave_minutes": total_early_leave_minutes,
            "total_present_days":        total_present_days,
        }

    # -----------------------------------------------------------------------
    # Soft delete (HR/Admin)
    # -----------------------------------------------------------------------
    @staticmethod
    def soft_delete_attendance(attendance_id: int) -> tuple[bool, str]:
        """
        Soft-deletes an attendance record (sets is_active=False).

        Returns (success, status_code).
        """
        record = db.session.get(Attendance, attendance_id)
        if not record or not record.is_active:
            return False, "NOT_FOUND"
        try:
            with transaction_or_flush(db.session):
                record.is_active = False
            logger.info(
                "ATTENDANCE_SOFT_DELETE",
                extra={"attendance_id": attendance_id}
            )
            return True, "SUCCESS"
        except Exception as e:
            logger.error(
                "ATTENDANCE_SOFT_DELETE_ERROR",
                extra={"attendance_id": attendance_id, "error": str(e)}
            )
            return False, "DATABASE_ERROR"
