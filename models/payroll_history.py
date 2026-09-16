from extensions import db
from models import BaseModel

class PayrollHistory(BaseModel):
    """
    PayrollHistory database model representing audit trails for payroll generations/modifications.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "payroll_histories"

    payroll_id = db.Column(
        db.Integer,
        db.ForeignKey("payrolls.id"),
        nullable=False,
        index=True
    )
    generated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False
    )
    generated_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    remarks = db.Column(db.Text, nullable=True)

    # Relationships
    payroll = db.relationship("Payroll")
    user = db.relationship("User")

    def __repr__(self):
        return f"<PayrollHistory payroll={self.payroll_id} at={self.generated_at}>"
