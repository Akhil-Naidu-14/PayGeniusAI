from datetime import datetime, UTC
from extensions import db

class BaseModel(db.Model):
    """
    Abstract base database model providing common columns.
    All application models should inherit from this.
    """
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)



# Import specific models to register them on the SQLAlchemy metadata in correct sequence
from models.role import Role
from models.user import User
from models.department import Department
from models.employee import Employee
from models.attendance import Attendance
from models.leave_type import LeaveType
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.payroll import Payroll
from models.payroll_history import PayrollHistory
from models.ai_conversation import AIConversation
from models.government_rule import GovernmentRule
from models.payroll_validation_log import PayrollValidationLog
from models.leave_encashment import LeaveEncashment

__all__ = [
    "BaseModel",
    "Role",
    "User",
    "Department",
    "Employee",
    "Attendance",
    "LeaveType",
    "LeaveBalance",
    "LeaveRequest",
    "Payroll",
    "PayrollHistory",
    "AIConversation",
    "GovernmentRule",
    "PayrollValidationLog",
    "LeaveEncashment",
]



