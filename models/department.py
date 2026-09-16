from extensions import db
from models import BaseModel

class Department(BaseModel):
    """
    Department database model representing organizational departments.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "departments"

    name = db.Column(db.String(100), unique=True, index=True, nullable=False)
    code = db.Column(db.String(20), unique=True, index=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    # Dynamic queryable one-to-many relationship with Employee (no cascade delete)
    employees = db.relationship(
        "Employee",
        back_populates="department",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<Department {self.name}>"
