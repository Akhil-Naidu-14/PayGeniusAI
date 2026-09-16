from decimal import Decimal
from sqlalchemy import UniqueConstraint
from extensions import db
from models import BaseModel

class Payroll(BaseModel):
    """
    Payroll database model representing employee monthly payslips.
    Inherits fields (id, created_at, updated_at, is_active) from BaseModel.
    """
    __tablename__ = "payrolls"

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False,
        index=True
    )
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)

    # Salary Components (Earnings)
    basic_salary = db.Column(db.Numeric(12, 2), nullable=False)
    hra = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    medical_allowance = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    travel_allowance = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    special_allowance = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    bonus = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    incentive = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    overtime_pay = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)

    # Computed Totals
    gross_salary = db.Column(db.Numeric(12, 2), nullable=False)

    # Deductions
    provident_fund = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    professional_tax = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    income_tax = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    loan_deduction = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    insurance_deduction = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)

    # Final
    total_deductions = db.Column(db.Numeric(12, 2), nullable=False)
    net_salary = db.Column(db.Numeric(12, 2), nullable=False)

    # Status
    status = db.Column(db.String(20), default="Generated", nullable=False, index=True)

    # Relationship to Employee (no cascade delete)
    employee = db.relationship("Employee")

    # Table constraints and indexes
    __table_args__ = (
        UniqueConstraint("employee_id", "month", "year", name="uq_employee_month_year"),
    )

    def __repr__(self):
        return f"<Payroll emp={self.employee_id} {self.year}-{self.month:02d}: net={self.net_salary}>"
