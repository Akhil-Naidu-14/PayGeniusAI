import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from extensions import db
from models.leave_encashment import LeaveEncashment, LeaveEncashmentStatus

logger = logging.getLogger(__name__)

def get_session():
    """
    Helper to resolve the actual SQLAlchemy Session from scoped_session proxy.
    """
    if hasattr(db.session, "_proxied"):
        return db.session._proxied
    elif callable(db.session):
        return db.session()
    return db.session

class LeaveEncashmentService:
    """
    LeaveEncashmentService manages processing, validations, and approvals for converting unused leaves to salary incentives.
    """

    @staticmethod
    def apply_encashment(employee_id: int, leave_type_id: int, year: int, days_requested: int) -> dict:
        """
        Validates leave balance and encashment rules, then records a Pending encashment request.
        """
        if days_requested <= 0:
            return {"success": False, "message": "Days requested must be greater than zero."}

        # Fetch models dynamically to avoid circular dependencies
        from models.leave_balance import LeaveBalance
        from models.leave_type import LeaveType
        from models.employee import Employee

        # Check unique constraint first
        existing_encashment = LeaveEncashment.query.filter_by(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            year=year,
            is_active=True
        ).first()
        if existing_encashment:
            return {"success": False, "message": "Leave encashment request already exists for this year."}

        # 1. Fetch LeaveBalance
        balance = LeaveBalance.query.filter_by(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            year=year,
            is_active=True
        ).first()

        if not balance:
            return {"success": False, "message": "Leave balance record not found for the given year."}

        # 2. Validate leave type is paid
        lt = db.session.get(LeaveType, leave_type_id)
        if not lt or not lt.is_active:
            return {"success": False, "message": "Leave type not found."}

        if not lt.is_paid:
            return {"success": False, "message": "Unpaid leave type cannot be encashed."}

        # Validate days requested <= remaining balance
        if days_requested > balance.remaining:
            return {"success": False, "message": f"Requested days ({days_requested}) exceed remaining balance ({balance.remaining})."}

        # 3. Compute amount
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return {"success": False, "message": "Employee not found."}

        monthly_basic = (Decimal(str(emp.basic_salary)) / Decimal("12.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        per_day_salary = (monthly_basic / Decimal("30.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_amount = (per_day_salary * Decimal(days_requested)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 4. Create LeaveEncashment record
        encashment = LeaveEncashment(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            year=year,
            days_requested=days_requested,
            amount_per_day=per_day_salary,
            total_amount=total_amount,
            status=LeaveEncashmentStatus.PENDING
        )

        session = get_session()
        try:
            with session.begin(nested=session.in_transaction()):
                db.session.add(encashment)
            return {
                "success": True,
                "message": "Leave encashment request submitted successfully.",
                "encashment_id": encashment.id,
                "total_amount": total_amount
            }
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to apply leave encashment: %s", str(e))
            return {"success": False, "message": f"Database error: {str(e)}"}

    @staticmethod
    def approve_encashment(encashment_id: int, approver_id: int) -> dict:
        """
        Approves a pending leave encashment, deducts balance, and adds incentive to payroll.
        """
        from models.leave_balance import LeaveBalance
        from models.employee import Employee
        from models.payroll import Payroll

        encashment = db.session.get(LeaveEncashment, encashment_id)
        if not encashment or not encashment.is_active:
            return {"success": False, "message": "Encashment request not found."}

        if encashment.status != LeaveEncashmentStatus.PENDING:
            return {"success": False, "message": "Only pending requests can be approved."}

        # Fetch LeaveBalance
        balance = LeaveBalance.query.filter_by(
            employee_id=encashment.employee_id,
            leave_type_id=encashment.leave_type_id,
            year=encashment.year,
            is_active=True
        ).first()

        if not balance:
            return {"success": False, "message": "Leave balance record not found."}

        if encashment.days_requested > balance.remaining:
            return {"success": False, "message": "Days requested exceed current remaining leave balance."}

        session = get_session()
        try:
            with session.begin(nested=session.in_transaction()):
                # 3. Deduct LeaveBalance.used
                balance.used += encashment.days_requested
                balance.remaining = balance.total_allocated - balance.used

                # 5. Update status
                encashment.status = LeaveEncashmentStatus.APPROVED
                encashment.approved_by = approver_id
                encashment.approved_at = datetime.now(timezone.utc)

                # 7. Insert payroll adjustment
                today = date.today()
                m, y = today.month, today.year
                
                payroll = Payroll.query.filter_by(
                    employee_id=encashment.employee_id,
                    month=m,
                    year=y,
                    is_active=True
                ).first()

                if payroll:
                    payroll.incentive += encashment.total_amount
                    payroll.gross_salary += encashment.total_amount
                    payroll.net_salary += encashment.total_amount
                else:
                    emp = db.session.get(Employee, encashment.employee_id)
                    payroll = Payroll(
                        employee_id=encashment.employee_id,
                        month=m,
                        year=y,
                        basic_salary=emp.basic_salary,
                        hra=Decimal("0.00"),
                        medical_allowance=Decimal("0.00"),
                        travel_allowance=Decimal("0.00"),
                        special_allowance=Decimal("0.00"),
                        bonus=Decimal("0.00"),
                        incentive=encashment.total_amount,
                        overtime_pay=Decimal("0.00"),
                        gross_salary=emp.basic_salary + encashment.total_amount,
                        provident_fund=Decimal("0.00"),
                        professional_tax=Decimal("0.00"),
                        income_tax=Decimal("0.00"),
                        loan_deduction=Decimal("0.00"),
                        insurance_deduction=Decimal("0.00"),
                        total_deductions=Decimal("0.00"),
                        net_salary=emp.basic_salary + encashment.total_amount,
                        status="Generated"
                    )
                    db.session.add(payroll)

            return {"success": True, "message": "Leave encashment request approved."}
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to approve leave encashment: %s", str(e))
            return {"success": False, "message": f"Database error: {str(e)}"}

    @staticmethod
    def reject_encashment(encashment_id: int, approver_id: int) -> dict:
        """
        Rejects a pending leave encashment request.
        """
        encashment = db.session.get(LeaveEncashment, encashment_id)
        if not encashment or not encashment.is_active:
            return {"success": False, "message": "Encashment request not found."}

        if encashment.status != LeaveEncashmentStatus.PENDING:
            return {"success": False, "message": "Only pending requests can be rejected."}

        session = get_session()
        try:
            with session.begin(nested=session.in_transaction()):
                encashment.status = LeaveEncashmentStatus.REJECTED
                encashment.approved_by = approver_id
                encashment.approved_at = datetime.now(timezone.utc)
            return {"success": True, "message": "Leave encashment request rejected."}
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to reject leave encashment: %s", str(e))
            return {"success": False, "message": f"Database error: {str(e)}"}
