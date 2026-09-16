from extensions import db
from models import BaseModel
from sqlalchemy import UniqueConstraint

class LeaveEncashmentStatus:
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CHOICES = [PENDING, APPROVED, REJECTED]

class LeaveEncashment(BaseModel):
    """
    LeaveEncashment database model representing employee requests to convert unused leave balances to pay.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "leave_encashments"

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False,
        index=True
    )
    leave_type_id = db.Column(
        db.Integer,
        db.ForeignKey("leave_types.id"),
        nullable=False
    )
    year = db.Column(
        db.Integer,
        nullable=False
    )
    days_requested = db.Column(
        db.Integer,
        nullable=False
    )
    amount_per_day = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )
    total_amount = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )
    status = db.Column(
        db.String(20),
        default=LeaveEncashmentStatus.PENDING,
        index=True,
        nullable=False
    )

    approved_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )
    approved_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    # Relationships (no cascade delete)
    employee = db.relationship("Employee")
    leave_type = db.relationship("LeaveType")
    approver = db.relationship("User")

    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type_id", "year", name="uq_encashment_year"),
    )

    def __repr__(self):
        return f"<LeaveEncashment emp={self.employee_id} type={self.leave_type_id} year={self.year} status={self.status}>"
