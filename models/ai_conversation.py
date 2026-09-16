from datetime import datetime, timezone
from extensions import db
from models import BaseModel

class AIConversation(BaseModel):
    """
    AIConversation database model representing historical Gemini AI analysis runs.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "ai_conversations"

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False,
        index=True
    )
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user = db.relationship("User")
    employee = db.relationship("Employee")

    def __repr__(self):
        return f"<AIConversation user={self.user_id} emp={self.employee_id} {self.year}-{self.month}>"
