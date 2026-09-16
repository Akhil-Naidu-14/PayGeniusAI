from extensions import db
from models import BaseModel

class RoleType:
    """Helper class defining standard Role names in the system."""
    ADMIN = "Administrator"
    HR = "HR Manager"
    EMPLOYEE = "Employee"


class Role(BaseModel):
    """
    Role database model representing access control privileges.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "roles"

    name = db.Column(db.String(64), unique=True, nullable=False, index=True)
    description = db.Column(db.String(256), nullable=True)

    # Dynamic queryable one-to-many relationship with User (no cascade delete)
    users = db.relationship(
        "User", 
        back_populates="role", 
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<Role {self.name}>"
