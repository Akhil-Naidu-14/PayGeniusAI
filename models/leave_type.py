from extensions import db
from models import BaseModel


class LeaveType(BaseModel):
    """
    Defines the types of leave available in the organisation (e.g. Annual,
    Sick, Maternity).  Each type carries a per-year quota and a paid/unpaid
    flag used by payroll processing.

    Inherits: id, created_at, updated_at, is_active  (BaseModel)
    """
    __tablename__ = "leave_types"

    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_paid = db.Column(db.Boolean, default=True, nullable=False)

    # Number of leave days allocated per employee per calendar year
    annual_quota = db.Column(db.Integer, nullable=False)

    # Back-references populated by LeaveBalance / LeaveRequest
    leave_balances = db.relationship(
        "LeaveBalance",
        back_populates="leave_type",
        lazy="dynamic"
    )
    leave_requests = db.relationship(
        "LeaveRequest",
        back_populates="leave_type",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<LeaveType {self.name} (quota={self.annual_quota}, paid={self.is_paid})>"
