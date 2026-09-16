from extensions import db
from models import BaseModel


class LeaveRequestStatus:
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"

    CHOICES = [PENDING, APPROVED, REJECTED, CANCELLED]


class LeaveRequest(BaseModel):
    """
    Represents an employee's request for a block of leave days.

    Overlap validation is enforced at the service layer, not via database
    constraints, to provide meaningful error messages and handle edge-cases
    (e.g. cancelled or rejected requests should not block new ones).

    Inherits: id, created_at, updated_at, is_active  (BaseModel)
    """
    __tablename__ = "leave_requests"

    # Employee making the request
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False,
        index=True
    )

    # Type of leave being requested
    leave_type_id = db.Column(
        db.Integer,
        db.ForeignKey("leave_types.id"),
        nullable=False,
        index=True
    )

    # Leave period
    start_date = db.Column(db.Date, nullable=False)
    end_date   = db.Column(db.Date, nullable=False)

    # Explicit count; computed by service layer (end_date - start_date + 1, minus weekends/holidays)
    days_requested = db.Column(db.Integer, nullable=False)

    reason = db.Column(db.Text, nullable=True)

    # Workflow status
    status = db.Column(
        db.String(20),
        nullable=False,
        default=LeaveRequestStatus.PENDING,
        index=True
    )

    # Approval metadata (nullable until actioned)
    approved_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    employee   = db.relationship("Employee",  back_populates="leave_requests")
    leave_type = db.relationship("LeaveType", back_populates="leave_requests")
    approver   = db.relationship("User",      back_populates="approved_leaves")

    def __repr__(self):
        return (
            f"<LeaveRequest emp={self.employee_id} "
            f"{self.start_date}→{self.end_date} [{self.status}]>"
        )
