from flask_login import UserMixin
from extensions import db
from models import BaseModel

class User(BaseModel, UserMixin):
    """
    User database model representing system accounts.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "users"

    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)

    # Foreign key referencing roles table (nullable for migration compatibility)
    role_id = db.Column(
        db.Integer, 
        db.ForeignKey("roles.id"), 
        nullable=True
    )

    # Relationship back to Role mapping back_populates
    role = db.relationship(
        "Role",
        back_populates="users"
    )

    # Optional Link to Employee (One-to-One / Unique ForeignKey)
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=True,
        unique=True
    )
    employee = db.relationship(
        "Employee",
        back_populates="user"
    )

    # Leave requests approved by this user (HR/Admin)
    approved_leaves = db.relationship(
        "LeaveRequest",
        back_populates="approver",
        lazy="dynamic",
        foreign_keys="LeaveRequest.approved_by"
    )

    def __repr__(self):
        return f"<User {self.username}>"

