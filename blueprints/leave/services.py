"""
LeaveService: Business logic for leave management.

Strict rules:
  - Overlap check: blocks NEW request if an APPROVED or PENDING request
    already occupies any date in the requested range for the same employee.
  - Balance integrity: remaining == total_allocated - used, always.
  - All mutations commit via db.session.commit() with explicit rollback on failure.
  - Attendance records for approved-leave dates are flipped to "On Leave".
  - No business logic leaks into routes.
"""

import logging
from datetime import date, datetime, timezone, timedelta

from extensions import db
from models.leave_request import LeaveRequest, LeaveRequestStatus
from models.leave_balance import LeaveBalance
from models.leave_type import LeaveType
from models.employee import Employee
from models.attendance import Attendance, AttendanceStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calc_days(start: date, end: date) -> int:
    """Inclusive calendar-day count between start and end."""
    return (end - start).days + 1


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _check_overlap(employee_id: int, start: date, end: date, exclude_id: int | None = None) -> bool:
    """
    Returns True if ANY active (Pending/Approved) leave request for the
    employee overlaps [start, end].
    Optionally excludes a specific request id (useful for edits).
    """
    q = LeaveRequest.query.filter(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.is_active   == True,
        LeaveRequest.status.in_([LeaveRequestStatus.PENDING, LeaveRequestStatus.APPROVED]),
        LeaveRequest.start_date  <= end,
        LeaveRequest.end_date    >= start,
    )
    if exclude_id:
        q = q.filter(LeaveRequest.id != exclude_id)
    return q.first() is not None


def _get_balance(employee_id: int, leave_type_id: int, year: int) -> LeaveBalance | None:
    return LeaveBalance.query.filter_by(
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        year=year,
        is_active=True,
    ).first()


def _flip_attendance_to_on_leave(employee_id: int, start: date, end: date) -> None:
    """
    For every calendar day in [start, end]:
      - Update existing attendance record to status "On Leave"
      - Create a stub "On Leave" record if none exists
    Must be called inside an active transaction (before db.session.commit()).
    """
    current = start
    while current <= end:
        record = Attendance.query.filter_by(
            employee_id=employee_id, date=current
        ).first()
        if record:
            record.status    = AttendanceStatus.ON_LEAVE
            record.is_active = True
        else:
            db.session.add(Attendance(
                employee_id=employee_id,
                date=current,
                status=AttendanceStatus.ON_LEAVE,
            ))
        current += timedelta(days=1)


# ---------------------------------------------------------------------------
# LeaveService
# ---------------------------------------------------------------------------

class LeaveService:

    # -------------------------------------------------------------------
    # Apply for leave (Employee)
    # -------------------------------------------------------------------
    @staticmethod
    def apply_leave(
        employee_id: int,
        leave_type_id: int,
        start_date: date,
        end_date: date,
        reason: str | None = None,
    ) -> tuple[bool, str, LeaveRequest | None]:
        """
        Creates a new Pending leave request.

        Returns (success, status_code, request | None).

        Status codes:
            SUCCESS          – request created
            NOT_FOUND        – employee or leave type not found / inactive
            INVALID_DATES    – end_date < start_date
            OVERLAP          – overlaps with existing Pending/Approved request
            NO_BALANCE       – no balance record for this type/year
            INSUFFICIENT     – remaining < days_requested
            DATABASE_ERROR
        """
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return False, "NOT_FOUND", None

        lt = db.session.get(LeaveType, leave_type_id)
        if not lt or not lt.is_active:
            return False, "NOT_FOUND", None

        if end_date < start_date:
            return False, "INVALID_DATES", None

        days = _calc_days(start_date, end_date)

        if _check_overlap(employee_id, start_date, end_date):
            return False, "OVERLAP", None

        year = start_date.year
        balance = _get_balance(employee_id, leave_type_id, year)
        if balance is None:
            return False, "NO_BALANCE", None
        if balance.remaining < days:
            return False, "INSUFFICIENT", None

        try:
            req = LeaveRequest(
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                start_date=start_date,
                end_date=end_date,
                days_requested=days,
                reason=reason.strip() if reason else None,
                status=LeaveRequestStatus.PENDING,
            )
            db.session.add(req)
            db.session.commit()
            logger.info(
                "LEAVE_APPLY",
                extra={"employee_id": employee_id, "days": days, "type": leave_type_id}
            )
            return True, "SUCCESS", req

        except Exception as e:
            db.session.rollback()
            logger.error("LEAVE_APPLY_ERROR", extra={"error": str(e)})
            return False, "DATABASE_ERROR", None

    # -------------------------------------------------------------------
    # Approve leave (HR/Admin)
    # -------------------------------------------------------------------
    @staticmethod
    def approve_leave(
        request_id: int,
        approver_user_id: int,
    ) -> tuple[bool, str, LeaveRequest | None]:
        """
        Approves a Pending leave request.
        Deducts days from the employee's leave balance.
        Flips attendance records to "On Leave".

        Status codes:
            SUCCESS
            NOT_FOUND        – request not found / inactive
            ALREADY_ACTIONED – request is not Pending
            NO_BALANCE       – balance record missing for the request's year
            INSUFFICIENT     – balance.remaining < days_requested
            DATABASE_ERROR
        """
        req = db.session.get(LeaveRequest, request_id)
        if not req or not req.is_active:
            return False, "NOT_FOUND", None

        if req.status != LeaveRequestStatus.PENDING:
            return False, "ALREADY_ACTIONED", None

        year = req.start_date.year
        balance = _get_balance(req.employee_id, req.leave_type_id, year)
        if balance is None:
            return False, "NO_BALANCE", None
        if balance.remaining < req.days_requested:
            return False, "INSUFFICIENT", None

        try:
            req.status      = LeaveRequestStatus.APPROVED
            req.approved_by = approver_user_id
            req.approved_at = _now_utc()

            balance.used      += req.days_requested
            balance.remaining  = balance.total_allocated - balance.used

            _flip_attendance_to_on_leave(req.employee_id, req.start_date, req.end_date)

            db.session.commit()
            logger.info(
                "LEAVE_APPROVE",
                extra={"request_id": request_id, "approver": approver_user_id}
            )
            return True, "SUCCESS", req

        except Exception as e:
            db.session.rollback()
            logger.error("LEAVE_APPROVE_ERROR", extra={"error": str(e)})
            return False, "DATABASE_ERROR", None

    # -------------------------------------------------------------------
    # Reject leave (HR/Admin)
    # -------------------------------------------------------------------
    @staticmethod
    def reject_leave(
        request_id: int,
        approver_user_id: int,
    ) -> tuple[bool, str, LeaveRequest | None]:
        """
        Rejects a Pending leave request. Does NOT touch the balance.

        Status codes:
            SUCCESS
            NOT_FOUND
            ALREADY_ACTIONED
            DATABASE_ERROR
        """
        req = db.session.get(LeaveRequest, request_id)
        if not req or not req.is_active:
            return False, "NOT_FOUND", None

        if req.status != LeaveRequestStatus.PENDING:
            return False, "ALREADY_ACTIONED", None

        try:
            req.status      = LeaveRequestStatus.REJECTED
            req.approved_by = approver_user_id
            req.approved_at = _now_utc()
            db.session.commit()
            logger.info(
                "LEAVE_REJECT",
                extra={"request_id": request_id, "approver": approver_user_id}
            )
            return True, "SUCCESS", req

        except Exception as e:
            db.session.rollback()
            logger.error("LEAVE_REJECT_ERROR", extra={"error": str(e)})
            return False, "DATABASE_ERROR", None

    # -------------------------------------------------------------------
    # Cancel leave (Employee — only if Pending)
    # -------------------------------------------------------------------
    @staticmethod
    def cancel_leave(
        request_id: int,
        requesting_employee_id: int,
    ) -> tuple[bool, str, LeaveRequest | None]:
        """
        Cancels a Pending leave request made by the requesting employee.

        Status codes:
            SUCCESS
            NOT_FOUND
            FORBIDDEN        – request belongs to a different employee
            NOT_PENDING      – only Pending requests may be cancelled
            DATABASE_ERROR
        """
        req = db.session.get(LeaveRequest, request_id)
        if not req or not req.is_active:
            return False, "NOT_FOUND", None

        if req.employee_id != requesting_employee_id:
            return False, "FORBIDDEN", None

        if req.status != LeaveRequestStatus.PENDING:
            return False, "NOT_PENDING", None

        try:
            req.status = LeaveRequestStatus.CANCELLED
            db.session.commit()
            logger.info("LEAVE_CANCEL", extra={"request_id": request_id})
            return True, "SUCCESS", req

        except Exception as e:
            db.session.rollback()
            logger.error("LEAVE_CANCEL_ERROR", extra={"error": str(e)})
            return False, "DATABASE_ERROR", None

    # -------------------------------------------------------------------
    # List requests (for views)
    # -------------------------------------------------------------------
    @staticmethod
    def list_employee_requests(employee_id: int) -> list[LeaveRequest]:
        """All active leave requests for a specific employee, newest first."""
        return (
            LeaveRequest.query
            .filter_by(employee_id=employee_id, is_active=True)
            .order_by(LeaveRequest.start_date.desc())
            .all()
        )

    @staticmethod
    def list_all_requests(status: str | None = None) -> list[LeaveRequest]:
        """All active requests (HR/Admin view), optionally filtered by status."""
        q = LeaveRequest.query.filter_by(is_active=True)
        if status:
            q = q.filter_by(status=status)
        return q.order_by(LeaveRequest.start_date.desc()).all()

    @staticmethod
    def list_employee_balances(employee_id: int, year: int) -> list[LeaveBalance]:
        """All active leave balances for an employee in a given year."""
        return (
            LeaveBalance.query
            .filter_by(employee_id=employee_id, year=year, is_active=True)
            .all()
        )

    @staticmethod
    def get_request(request_id: int) -> LeaveRequest | None:
        return LeaveRequest.query.filter_by(id=request_id, is_active=True).first()
