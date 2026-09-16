from decimal import Decimal
from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from extensions import db
from models import BaseModel


class AttendanceStatus:
    PRESENT = "Present"
    ABSENT = "Absent"
    HALF_DAY = "Half Day"
    ON_LEAVE = "On Leave"
    CHOICES = [PRESENT, ABSENT, HALF_DAY, ON_LEAVE]


class Attendance(BaseModel):
    """
    Attendance database model representing daily employee attendance records.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.

    Index strategy:
    - ix_employee_date (employee_id, date): composite; covers all queries
      by employee or by employee+date. Replaces individual column indexes.
    - ix_attendance_status: single index on status for status-based filtering.
    - uq_employee_date: enforces one record per employee per calendar day.
    """
    __tablename__ = "attendances"

    # Identification — index=False; covered by composite ix_employee_date
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False,
        index=False
    )
    # index=False; covered by composite ix_employee_date
    date = db.Column(db.Date, nullable=False, index=False)

    # Check-In/Out timestamps (timezone-aware)
    check_in = db.Column(db.DateTime(timezone=True), nullable=True)
    check_out = db.Column(db.DateTime(timezone=True), nullable=True)

    # Computed fields (stored, not calculated dynamically)
    working_hours = db.Column(db.Numeric(6, 2), nullable=True)
    overtime_hours = db.Column(
        db.Numeric(6, 2), default=Decimal("0.00"), nullable=False
    )
    late_minutes = db.Column(db.Integer, default=0, nullable=False)
    early_leave_minutes = db.Column(db.Integer, default=0, nullable=False)

    # Status — index=False; covered by explicit ix_attendance_status below
    status = db.Column(
        db.String(20),
        nullable=False,
        default=AttendanceStatus.PRESENT,
        index=False
    )

    # Relationships (no cascade delete; soft-delete via BaseModel.is_active)
    employee = db.relationship("Employee", back_populates="attendances")

    # Explicit table constraints and named indexes
    __table_args__ = (
        # Composite unique constraint — one record per employee per day
        UniqueConstraint("employee_id", "date", name="uq_employee_date"),
        # Composite index — optimises employee lookups and date range queries
        Index("ix_employee_date", "employee_id", "date"),
        # Single-column index for status-based payroll/HR queries
        Index("ix_attendance_status", "status"),
        # Check constraints — prevent negative stored computed values
        CheckConstraint("overtime_hours >= 0", name="ck_overtime_non_negative"),
        CheckConstraint("late_minutes >= 0", name="ck_late_non_negative"),
        CheckConstraint("early_leave_minutes >= 0", name="ck_early_leave_non_negative"),
    )

    def __repr__(self):
        return f"<Attendance {self.employee_id} on {self.date}: {self.status}>"
