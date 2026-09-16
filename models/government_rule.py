from extensions import db
from models import BaseModel

class GovernmentRule(BaseModel):
    """
    GovernmentRule database model representing legal rules and caps (e.g. PF percentage, tax rates).
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "government_rules"

    rule_type = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    value = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )
    description = db.Column(
        db.Text,
        nullable=True
    )
    effective_from = db.Column(
        db.Date,
        nullable=False
    )
    effective_to = db.Column(
        db.Date,
        nullable=True
    )

    def __repr__(self):
        return f"<GovernmentRule {self.rule_type} value={self.value}>"
