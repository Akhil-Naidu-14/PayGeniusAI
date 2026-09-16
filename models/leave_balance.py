from sqlalchemy import UniqueConstraint
from extensions import db
from models import BaseModel


class LeaveBalance(BaseModel):
    """
    Tracks the leave allocation and usage for a single employee, leave type,
    and calendar year.

    The `remaining` field is stored explicitly (= total_allocated - used) and
    must be kept in sync by the service layer — no triggers or computed columns
    are used to keep the model migration-agnostic.

    Constraints:
        uq_leave_balance_emp_type_year: one row per (employee, type, year).

    Inherits: id, created_at, updated_at, is_active  (BaseModel)
    """
    __tablename__ = "leave_balances"

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False,
        index=True
    )
    leave_type_id = db.Column(
        db.Integer,
        db.ForeignKey("leave_types.id"),
        nullable=False,
        index=True
    )
    year = db.Column(db.Integer, nullable=False)

    total_allocated = db.Column(db.Integer, nullable=False)
    used = db.Column(db.Integer, default=0, nullable=False)
    remaining = db.Column(db.Integer, nullable=False)

    # Relationships
    employee = db.relationship("Employee", back_populates="leave_balances")
    leave_type = db.relationship("LeaveType", back_populates="leave_balances")

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "leave_type_id", "year",
            name="uq_leave_balance_emp_type_year"
        ),
    )

    def __repr__(self):
        return (
            f"<LeaveBalance emp={self.employee_id} "
            f"type={self.leave_type_id} year={self.year} "
            f"remaining={self.remaining}>"
        )
