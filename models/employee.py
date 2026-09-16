from extensions import db
from models import BaseModel

class EmployeeStatus:
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    RESIGNED = "Resigned"
    
    CHOICES = [ACTIVE, INACTIVE, RESIGNED]

class Employee(BaseModel):

    """
    Employee database model representing payrolled organization employees.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "employees"

    # Identification
    employee_code = db.Column(db.String(20), unique=True, index=True, nullable=False)

    # Personal Info
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    address = db.Column(db.Text, nullable=True)

    # Employment Info
    joining_date = db.Column(db.Date, nullable=False)
    employment_type = db.Column(db.String(50), nullable=False)

    # Salary
    basic_salary = db.Column(db.Numeric(12, 2), nullable=False)

    # Bank Info
    bank_account_number = db.Column(db.String(50), nullable=True)
    ifsc_code = db.Column(db.String(20), nullable=True)
    pan_number = db.Column(db.String(20), nullable=True)
    aadhaar_number = db.Column(db.String(20), nullable=True)

    # Emergency Contact
    emergency_contact = db.Column(db.String(20), nullable=True)

    # Status
    status = db.Column(db.String(20), default="Active", nullable=False, index=True)

    # Department Relationship (Foreign Key references departments.id)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=False,
        index=True
    )
    
    # Relationship back to Department mapping back_populates
    department = db.relationship(
        "Department",
        back_populates="employees"
    )

    attendances = db.relationship(
        "Attendance",
        back_populates="employee",
        lazy="dynamic"
    )

    leave_balances = db.relationship(
        "LeaveBalance",
        back_populates="employee",
        lazy="dynamic"
    )

    leave_requests = db.relationship(
        "LeaveRequest",
        back_populates="employee",
        lazy="dynamic"
    )

    user = db.relationship(
        "User",
        back_populates="employee",
        uselist=False
    )


    # Composite Index on name for optimized searching
    __table_args__ = (
        db.Index("ix_employees_full_name", "first_name", "last_name"),
    )

    def __repr__(self):
        return f"<Employee {self.first_name} {self.last_name} ({self.employee_code})>"
