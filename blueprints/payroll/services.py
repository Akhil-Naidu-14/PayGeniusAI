import calendar
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import extract

from extensions import db
from models.payroll import Payroll
from models.payroll_history import PayrollHistory
from models.employee import Employee
from models.attendance import Attendance, AttendanceStatus
from models.leave_request import LeaveRequest, LeaveRequestStatus
from models.government_rule import GovernmentRule
from models.payroll_validation_log import PayrollValidationLog

logger = logging.getLogger(__name__)

def _q(amount: Decimal) -> Decimal:
    """Helper to quantize a Decimal to 2 decimal places using ROUND_HALF_UP."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

class PayrollService:
    """
    PayrollService encapsulates all core calculation and business logic for payroll processing.
    """

    @staticmethod
    def _get_active_rule_value(rule_type: str, as_of: date) -> Decimal | None:
        """
        Looks up active GovernmentRule for rule_type effective on or before as_of date.
        """
        rule = (
            GovernmentRule.query
            .filter(GovernmentRule.rule_type == rule_type)
            .filter(GovernmentRule.is_active == True)
            .filter(GovernmentRule.effective_from <= as_of)
            .filter((GovernmentRule.effective_to.is_(None)) | (GovernmentRule.effective_to >= as_of))
            .order_by(GovernmentRule.effective_from.desc())
            .first()
        )
        return Decimal(str(rule.value)) if rule else None

    @staticmethod
    def calculate_overtime_pay(overtime_hours: Decimal, basic_salary: Decimal) -> Decimal:
        """
        Calculates overtime pay: overtime_hours * (basic_salary / 160)
        """
        if overtime_hours <= 0 or basic_salary <= 0:
            return Decimal("0.00")
        
        pay = overtime_hours * (basic_salary / Decimal("160.00"))
        # Round using ROUND_HALF_UP
        rounded_pay = pay.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return max(Decimal("0.00"), rounded_pay)

    @staticmethod
    def calculate_unpaid_leave_deduction(basic_salary: Decimal, unpaid_days: int) -> Decimal:
        """
        Calculates unpaid leave deduction: (basic_salary / 30) * unpaid_days
        """
        if unpaid_days <= 0 or basic_salary <= 0:
            return Decimal("0.00")

        deduction = (basic_salary / Decimal("30.00")) * Decimal(unpaid_days)
        rounded_deduction = deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return max(Decimal("0.00"), rounded_deduction)

    @staticmethod
    def calculate_monthly_attendance_summary(employee_id: int, month: int, year: int) -> dict:
        """
        Fetches active attendance records and returns working_hours, overtime_hours, and present days.
        """
        records = Attendance.query.filter_by(
            employee_id=employee_id,
            is_active=True
        ).filter(
            extract("month", Attendance.date) == month,
            extract("year", Attendance.date) == year
        ).all()

        working_hours = Decimal("0.00")
        overtime_hours = Decimal("0.00")
        total_present_days = 0

        for r in records:
            if r.working_hours is not None:
                working_hours += Decimal(str(r.working_hours))
            if r.overtime_hours is not None:
                overtime_hours += Decimal(str(r.overtime_hours))
            if r.status == AttendanceStatus.PRESENT:
                total_present_days += 1

        return {
            "working_hours": working_hours,
            "overtime_hours": overtime_hours,
            "total_present_days": total_present_days
        }

    @staticmethod
    def calculate_unpaid_leave_days(employee_id: int, month: int, year: int) -> int:
        """
        Calculates total active approved unpaid leave days falling within the target month.
        """
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])

        leaves = LeaveRequest.query.filter_by(
            employee_id=employee_id,
            status=LeaveRequestStatus.APPROVED,
            is_active=True
        ).all()

        unpaid_days = 0
        for req in leaves:
            if not req.leave_type.is_paid:
                # Calculate overlap between request range and month range
                overlap_start = max(req.start_date, month_start)
                overlap_end = min(req.end_date, month_end)
                if overlap_start <= overlap_end:
                    unpaid_days += (overlap_end - overlap_start).days + 1

        return unpaid_days

    @staticmethod
    def generate_monthly_payroll(
        employee_id: int,
        month: int,
        year: int,
        generated_by: int,
        hra: Decimal = Decimal("0.00"),
        medical_allowance: Decimal = Decimal("0.00"),
        travel_allowance: Decimal = Decimal("0.00"),
        special_allowance: Decimal = Decimal("0.00"),
        bonus: Decimal = Decimal("0.00"),
        incentive: Decimal = Decimal("0.00"),
        provident_fund: Decimal = Decimal("0.00"),
        professional_tax: Decimal = Decimal("0.00"),
        income_tax: Decimal = Decimal("0.00"),
        loan_deduction: Decimal = Decimal("0.00"),
        insurance_deduction: Decimal = Decimal("0.00"),
        apply_rule_defaults: bool = False
    ) -> dict:
        """
        Generates and saves monthly payroll for an employee.
        """
        # Force HRA and Special Allowance to 0.00 as per business rules
        hra = Decimal("0.00")
        special_allowance = Decimal("0.00")
        medical_allowance = Decimal(str(medical_allowance))
        travel_allowance = Decimal(str(travel_allowance))
        bonus = Decimal(str(bonus))
        incentive = Decimal(str(incentive))
        provident_fund = Decimal(str(provident_fund))
        professional_tax = Decimal(str(professional_tax))
        income_tax = Decimal(str(income_tax))
        loan_deduction = Decimal(str(loan_deduction))
        insurance_deduction = Decimal(str(insurance_deduction))

        # 1. Prevent duplicate payroll
        existing = Payroll.query.filter_by(
            employee_id=employee_id,
            month=month,
            year=year,
            is_active=True
        ).first()
        if existing:
            return {"success": False, "message": "Payroll already exists for this employee for the given month and year."}

        # 2. Fetch employee
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return {"success": False, "message": "Employee not found or inactive."}

        annual_basic = Decimal(str(emp.basic_salary))
        monthly_basic = _q(annual_basic / Decimal("12.00"))
        basic_salary = monthly_basic

        # 3. Fetch attendance summary
        att_summary = PayrollService.calculate_monthly_attendance_summary(employee_id, month, year)
        overtime_hours = att_summary["overtime_hours"]

        # 4. Fetch unpaid leave days
        unpaid_days = PayrollService.calculate_unpaid_leave_days(employee_id, month, year)
        unpaid_deduction = PayrollService.calculate_unpaid_leave_deduction(basic_salary, unpaid_days)

        # 5. Overtime Pay
        overtime_pay = PayrollService.calculate_overtime_pay(overtime_hours, basic_salary)

        # Apply rule defaults if requested
        if apply_rule_defaults:
            if medical_allowance == Decimal("0.00"):
                medical_allowance = _q(basic_salary * Decimal("0.05"))
            if travel_allowance == Decimal("0.00"):
                travel_allowance = _q(basic_salary * Decimal("0.05"))

            as_of = date(year, month, 1)

            # Bonus & Tenure Incentive calculation
            bonus_percent = PayrollService._get_active_rule_value("BONUS_PERCENTAGE", as_of) or Decimal("8.33")
            incentive_percent = PayrollService._get_active_rule_value("INCENTIVE_PERCENTAGE", as_of) or Decimal("5.00")

            service_months = max(0, (year - emp.joining_date.year) * 12 + (month - emp.joining_date.month))
            tenure_years = service_months // 12

            if bonus == Decimal("0.00") and service_months >= 1:
                bonus = _q(basic_salary * (bonus_percent / Decimal("100.00")))
            if incentive == Decimal("0.00") and tenure_years >= 1:
                incentive = _q(basic_salary * (incentive_percent / Decimal("100.00")) * Decimal(tenure_years))

            pf_percent = PayrollService._get_active_rule_value("PF_PERCENTAGE", as_of) or Decimal("12.00")
            pt_amount = PayrollService._get_active_rule_value("PROFESSIONAL_TAX", as_of) or Decimal("200.00")
            tax_percent = PayrollService._get_active_rule_value("INCOME_TAX", as_of) or Decimal("5.00")

            if provident_fund == Decimal("0.00"):
                provident_fund = _q(basic_salary * (pf_percent / Decimal("100.00")))
            if professional_tax == Decimal("0.00"):
                professional_tax = _q(pt_amount)

            prelim_gross = (
                basic_salary
                + bonus
                + incentive
                + overtime_pay
            )
            taxable_base = max(
                Decimal("0.00"),
                prelim_gross - provident_fund - professional_tax - medical_allowance - travel_allowance
            )
            if income_tax == Decimal("0.00"):
                income_tax = _q(taxable_base * (tax_percent / Decimal("100.00")))

        # 6. Compute gross salary
        gross_salary = _q(
            basic_salary
            + bonus
            + incentive
            + overtime_pay
        )

        # 7. Compute total deductions
        total_deductions = _q(
            provident_fund
            + professional_tax
            + income_tax
            + loan_deduction
            + insurance_deduction
            + unpaid_deduction
            + medical_allowance
            + travel_allowance
        )

        # 8. net_salary = gross_salary - total_deductions
        net_salary = _q(gross_salary - total_deductions)

        # Guard against negative values
        gross_salary = max(Decimal("0.00"), gross_salary)
        total_deductions = max(Decimal("0.00"), total_deductions)
        net_salary = max(Decimal("0.00"), net_salary)

        # 9. Store payroll record
        payroll = Payroll(
            employee_id=employee_id,
            month=month,
            year=year,
            basic_salary=basic_salary,
            hra=Decimal("0.00"),
            medical_allowance=medical_allowance,
            travel_allowance=travel_allowance,
            special_allowance=Decimal("0.00"),
            bonus=bonus,
            incentive=incentive,
            overtime_pay=overtime_pay,
            gross_salary=gross_salary,
            provident_fund=provident_fund,
            professional_tax=professional_tax,
            income_tax=income_tax,
            loan_deduction=loan_deduction,
            insurance_deduction=insurance_deduction,
            total_deductions=total_deductions,
            net_salary=net_salary,
            status="Generated"
        )

        # 10. Store payroll history record
        history = PayrollHistory(
            payroll=payroll,
            generated_at=datetime.now(timezone.utc),
            generated_by=generated_by,
            remarks=f"Payroll generated for {year}-{month:02d}."
        )

        # 11. Transaction block commit
        try:
            db.session.add(payroll)
            db.session.add(history)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Error committing payroll generation transaction: %s", str(e))
            return {"success": False, "message": "Database transaction failed."}

        # 12. Return structured result
        return {
            "success": True,
            "gross_salary": gross_salary,
            "net_salary": net_salary,
            "overtime_hours": overtime_hours,
            "unpaid_days": unpaid_days
        }

    @staticmethod
    def detect_payroll_anomaly(employee_id: int, month: int, year: int) -> dict:
        """
        Runs deterministic rule-based anomaly detection on a payroll record.
        """
        # Fetch current payroll record
        payroll = Payroll.query.filter_by(
            employee_id=employee_id,
            month=month,
            year=year,
            is_active=True
        ).first()
        
        if not payroll:
            return {
                "anomaly": False,
                "severity": None,
                "reasons": ["Current payroll record not found"],
                "metrics": {
                    "current_net_salary": Decimal("0.00"),
                    "avg_net_salary": Decimal("0.00"),
                    "overtime_hours": Decimal("0.00"),
                    "unpaid_leave_days": 0
                }
            }

        # Calculate helper for last 6 months list of tuples
        def get_last_6_months_tuples(m: int, y: int) -> list[tuple[int, int]]:
            res = []
            curr_m, curr_y = m, y
            for _ in range(6):
                curr_m -= 1
                if curr_m == 0:
                    curr_m = 12
                    curr_y -= 1
                res.append((curr_m, curr_y))
            return res

        last_6_tuples = get_last_6_months_tuples(month, year)

        # Fetch last 6 months payroll records
        historical_payrolls = Payroll.query.filter(
            Payroll.employee_id == employee_id,
            Payroll.is_active == True
        ).all()

        historical_records = [
            p for p in historical_payrolls
            if (p.month, p.year) in last_6_tuples
        ]

        # Calculate current metrics
        att_summary = PayrollService.calculate_monthly_attendance_summary(employee_id, month, year)
        current_working_hours = att_summary["working_hours"]
        current_overtime_hours = att_summary["overtime_hours"]
        current_unpaid_leave_days = PayrollService.calculate_unpaid_leave_days(employee_id, month, year)
        current_net_salary = payroll.net_salary

        # Default metrics structure
        metrics = {
            "current_net_salary": current_net_salary,
            "avg_net_salary": Decimal("0.00"),
            "overtime_hours": current_overtime_hours,
            "unpaid_leave_days": current_unpaid_leave_days
        }

        # If no historical data exists, return anomaly=False, severity=None
        if not historical_records:
            return {
                "anomaly": False,
                "severity": None,
                "reasons": [],
                "metrics": metrics
            }

        n = len(historical_records)
        
        # Calculate historical averages
        avg_net_salary = sum((p.net_salary for p in historical_records), Decimal("0.00")) / Decimal(str(n))
        
        # Get historical overtime and working hours from attendance
        hist_overtimes = []
        hist_working = []
        for p in historical_records:
            summary = PayrollService.calculate_monthly_attendance_summary(employee_id, p.month, p.year)
            hist_overtimes.append(summary["overtime_hours"])
            hist_working.append(summary["working_hours"])

        avg_overtime = sum(hist_overtimes, Decimal("0.00")) / Decimal(str(n))

        # Update metrics with correct average
        metrics["avg_net_salary"] = avg_net_salary

        reasons = []

        # Apply Rules
        # RULE 1: current net_salary > avg_net_salary * 1.5
        if current_net_salary > avg_net_salary * Decimal("1.5"):
            reasons.append("Salary spike detected")

        # RULE 2: current overtime_hours > avg_overtime * 2
        if current_overtime_hours > avg_overtime * Decimal("2"):
            reasons.append("Overtime spike detected")

        # RULE 3: unpaid leave days > 10
        if current_unpaid_leave_days > 10:
            reasons.append("Excessive unpaid leave")

        # RULE 4: working_hours < 50% of expected monthly hours (160) -> 80 hours
        if current_working_hours < Decimal("80.00"):
            reasons.append("Low attendance month")

        # RULE 5: net_salary <= 0
        if current_net_salary <= Decimal("0.00"):
            reasons.append("Invalid payroll calculation")

        # Calculate severity and anomaly
        num_rules = len(reasons)
        if num_rules > 0:
            anomaly = True
            if num_rules == 1:
                severity = "Low"
            elif num_rules == 2:
                severity = "Medium"
            else:
                severity = "High"
        else:
            anomaly = False
            severity = None

        return {
            "anomaly": anomaly,
            "severity": severity,
            "reasons": reasons,
            "metrics": metrics
        }

    @staticmethod
    def validate_payroll_against_government_rules(payroll_id: int) -> dict:
        """
        Validates a generated payroll record against government compliance rules.
        Saves validation logs in the database.
        """
        payroll = db.session.get(Payroll, payroll_id)
        if not payroll or not payroll.is_active:
            return {
                "overall_status": "FAIL",
                "violations": ["Payroll record not found."],
                "logs_created": 0
            }

        # Calculate payroll month start date
        payroll_month_date = date(payroll.year, payroll.month, 1)

        # Query active rules for this pay period
        rules = GovernmentRule.query.filter(
            GovernmentRule.is_active == True,
            GovernmentRule.effective_from <= payroll_month_date
        ).filter(
            (GovernmentRule.effective_to == None) | (GovernmentRule.effective_to >= payroll_month_date)
        ).all()

        logs_created = 0
        violations = []
        overall_status = "PASS"

        try:
            for rule in rules:
                status = "PASS"
                message = ""

                # RULE 1 — PF Percentage Validation
                if rule.rule_type == "PF_PERCENTAGE":
                    expected_pf = payroll.basic_salary * (rule.value / Decimal("100.00"))
                    expected_pf = expected_pf.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if payroll.provident_fund != expected_pf:
                        status = "WARNING"
                        message = f"PF mismatch: expected {expected_pf:,.2f}, got {payroll.provident_fund:,.2f}."
                    else:
                        message = f"PF matches expected value of {expected_pf:,.2f}."

                # RULE 2 — Minimum Wage Validation
                elif rule.rule_type == "MINIMUM_WAGE":
                    if payroll.basic_salary < rule.value:
                        status = "FAIL"
                        message = f"Basic salary {payroll.basic_salary:,.2f} is below minimum wage threshold of {rule.value:,.2f}."
                    else:
                        message = "Basic salary satisfies minimum wage threshold."

                # RULE 3 — Maximum Deduction Cap
                elif rule.rule_type == "MAX_DEDUCTION_CAP":
                    max_allowed = payroll.gross_salary * (rule.value / Decimal("100.00"))
                    max_allowed = max_allowed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if payroll.total_deductions > max_allowed:
                        status = "FAIL"
                        message = f"Total deductions {payroll.total_deductions:,.2f} exceeds cap of {rule.value}% of gross salary ({max_allowed:,.2f})."
                    else:
                        message = f"Total deductions within the cap of {rule.value}%."

                # RULE 4 — Professional Tax (Flat or Slab)
                elif rule.rule_type == "PROFESSIONAL_TAX":
                    if payroll.professional_tax != rule.value:
                        status = "WARNING"
                        message = f"Professional tax mismatch: expected {rule.value:,.2f}, got {payroll.professional_tax:,.2f}."
                    else:
                        message = "Professional tax matches."

                # RULE 5 — Income Tax
                elif rule.rule_type == "INCOME_TAX":
                    if payroll.income_tax != rule.value:
                        status = "WARNING"
                        message = f"Income tax mismatch: expected {rule.value:,.2f}, got {payroll.income_tax:,.2f}."
                    else:
                        message = "Income tax matches."

                else:
                    # Skip unknown rule types
                    continue

                # Record the log entry
                log_entry = PayrollValidationLog(
                    payroll_id=payroll_id,
                    rule_type=rule.rule_type,
                    validation_status=status,
                    message=message,
                    validated_at=datetime.now(timezone.utc)
                )
                db.session.add(log_entry)
                logs_created += 1

                if status != "PASS":
                    violations.append(f"[{rule.rule_type}] {message}")
                    if status == "FAIL":
                        overall_status = "FAIL"
                    elif status == "WARNING" and overall_status != "FAIL":
                        overall_status = "WARNING"

            db.session.commit()

        except Exception as tx_err:
            db.session.rollback()
            logger.error("Transaction failed during payroll government rule validation: %s", str(tx_err))
            return {
                "overall_status": "FAIL",
                "violations": [f"Database transaction error: {str(tx_err)}"],
                "logs_created": 0
            }

        return {
            "overall_status": overall_status,
            "violations": violations,
            "logs_created": logs_created
        }


