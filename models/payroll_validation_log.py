from datetime import datetime, timezone
from extensions import db
from models import BaseModel

class PayrollValidationLog(BaseModel):
    """
    PayrollValidationLog database model representing rule check results for generated payroll.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "payroll_validation_logs"

    payroll_id = db.Column(
        db.Integer,
        db.ForeignKey("payrolls.id"),
        nullable=False,
        index=True
    )
    rule_type = db.Column(
        db.String(50),
        nullable=False
    )
    validation_status = db.Column(
        db.String(20),
        nullable=False
    )
    message = db.Column(
        db.Text,
        nullable=True
    )
    validated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship to Payroll (no cascade delete)
    payroll = db.relationship("Payroll")

    def __repr__(self):
        return f"<PayrollValidationLog payroll={self.payroll_id} status={self.validation_status} rule={self.rule_type}>"
