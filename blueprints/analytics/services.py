from datetime import date
from decimal import Decimal
from sqlalchemy import extract, func

from extensions import db
from models.payroll import Payroll
from models.department import Department
from models.employee import Employee
from models.attendance import Attendance
from models.leave_request import LeaveRequest
from models.payroll_validation_log import PayrollValidationLog

class AnalyticsService:
    """
    AnalyticsService aggregates system-wide statistics for reporting and dashboard visualizations.
    """

    @staticmethod
    def get_payroll_trend(last_n_months: int = 6) -> dict:
        """
        Aggregates total payroll net salary cost per month for the last N months chronologically.
        """
        today = date.today()
        curr_m = today.month
        curr_y = today.year

        months_list = []
        y, m = curr_y, curr_m
        for _ in range(last_n_months):
            months_list.append((m, y))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        
        months_list.reverse()

        labels = []
        total_costs = []

        for m, y in months_list:
            labels.append(f"{y}-{m:02d}")
            total_net = db.session.query(func.sum(Payroll.net_salary)).filter(
                Payroll.month == m,
                Payroll.year == y,
                Payroll.is_active == True
            ).scalar() or Decimal("0.00")
            total_costs.append(float(total_net))

        return {
            "labels": labels,
            "total_cost": total_costs
        }

    @staticmethod
    def get_department_salary_distribution() -> dict:
        """
        Aggregates total basic salary cost across active employees grouped by department.
        """
        depts = Department.query.filter_by(is_active=True).all()
        
        departments = []
        total_salaries = []

        for dept in depts:
            dept_sum = db.session.query(func.sum(Employee.basic_salary)).filter(
                Employee.department_id == dept.id,
                Employee.is_active == True
            ).scalar() or Decimal("0.00")
            
            departments.append(dept.name)
            total_salaries.append(float(dept_sum))

        return {
            "departments": departments,
            "total_salaries": total_salaries
        }

    @staticmethod
    def get_attendance_trend(last_n_months: int = 6) -> dict:
        """
        Aggregates total working hours and overtime hours per month for the last N months chronologically.
        """
        today = date.today()
        curr_m = today.month
        curr_y = today.year

        months_list = []
        y, m = curr_y, curr_m
        for _ in range(last_n_months):
            months_list.append((m, y))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        
        months_list.reverse()

        labels = []
        working_hours = []
        overtime_hours = []

        for m, y in months_list:
            labels.append(f"{y}-{m:02d}")
            
            res = db.session.query(
                func.sum(Attendance.working_hours),
                func.sum(Attendance.overtime_hours)
            ).filter(
                extract("month", Attendance.date) == m,
                extract("year", Attendance.date) == y,
                Attendance.is_active == True
            ).first()

            w_hrs = res[0] or Decimal("0.00")
            o_hrs = res[1] or Decimal("0.00")
            
            working_hours.append(float(w_hrs))
            overtime_hours.append(float(o_hrs))

        return {
            "labels": labels,
            "working_hours": working_hours,
            "overtime_hours": overtime_hours
        }

    @staticmethod
    def get_leave_statistics(year: int) -> dict:
        """
        Aggregates leave request count metrics for a specific calendar year.
        """
        total = LeaveRequest.query.filter(
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.is_active == True
        ).count()

        approved = LeaveRequest.query.filter(
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.status == "Approved",
            LeaveRequest.is_active == True
        ).count()

        rejected = LeaveRequest.query.filter(
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.status == "Rejected",
            LeaveRequest.is_active == True
        ).count()

        cancelled = LeaveRequest.query.filter(
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.status == "Cancelled",
            LeaveRequest.is_active == True
        ).count()

        return {
            "total_requests": total,
            "approved": approved,
            "rejected": rejected,
            "cancelled": cancelled
        }

    @staticmethod
    def get_compliance_risk_summary(month: int, year: int) -> dict:
        """
        Aggregates government rule validation logs counts per status level for a given month/year.
        """
        pass_count = db.session.query(PayrollValidationLog).join(Payroll).filter(
            Payroll.month == month,
            Payroll.year == year,
            PayrollValidationLog.validation_status == "PASS",
            PayrollValidationLog.is_active == True,
            Payroll.is_active == True
        ).count()

        warning_count = db.session.query(PayrollValidationLog).join(Payroll).filter(
            Payroll.month == month,
            Payroll.year == year,
            PayrollValidationLog.validation_status == "WARNING",
            PayrollValidationLog.is_active == True,
            Payroll.is_active == True
        ).count()

        fail_count = db.session.query(PayrollValidationLog).join(Payroll).filter(
            Payroll.month == month,
            Payroll.year == year,
            PayrollValidationLog.validation_status == "FAIL",
            PayrollValidationLog.is_active == True,
            Payroll.is_active == True
        ).count()

        return {
            "pass": pass_count,
            "warning": warning_count,
            "fail": fail_count
        }

    @staticmethod
    def get_personal_payroll_trend(employee_id: int, last_n_months: int = 6) -> dict:
        """
        Aggregates total personal net salary trend for a given employee.
        """
        today = date.today()
        curr_m = today.month
        curr_y = today.year

        months_list = []
        y, m = curr_y, curr_m
        for _ in range(last_n_months):
            months_list.append((m, y))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        
        months_list.reverse()

        labels = []
        total_costs = []

        for m, y in months_list:
            labels.append(f"{y}-{m:02d}")
            total_net = db.session.query(func.sum(Payroll.net_salary)).filter(
                Payroll.employee_id == employee_id,
                Payroll.month == m,
                Payroll.year == y,
                Payroll.is_active == True
            ).scalar() or Decimal("0.00")
            total_costs.append(float(total_net))

        return {
            "labels": labels,
            "total_cost": total_costs
        }

    @staticmethod
    def get_personal_attendance_trend(employee_id: int, last_n_months: int = 6) -> dict:
        """
        Aggregates total working hours and overtime hours per month for a given employee.
        """
        today = date.today()
        curr_m = today.month
        curr_y = today.year

        months_list = []
        y, m = curr_y, curr_m
        for _ in range(last_n_months):
            months_list.append((m, y))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        
        months_list.reverse()

        labels = []
        working_hours = []
        overtime_hours = []

        for m, y in months_list:
            labels.append(f"{y}-{m:02d}")
            
            res = db.session.query(
                func.sum(Attendance.working_hours),
                func.sum(Attendance.overtime_hours)
            ).filter(
                Attendance.employee_id == employee_id,
                extract("month", Attendance.date) == m,
                extract("year", Attendance.date) == y,
                Attendance.is_active == True
            ).first()

            w_hrs = res[0] or Decimal("0.00")
            o_hrs = res[1] or Decimal("0.00")
            
            working_hours.append(float(w_hrs))
            overtime_hours.append(float(o_hrs))

        return {
            "labels": labels,
            "working_hours": working_hours,
            "overtime_hours": overtime_hours
        }

    @staticmethod
    def get_personal_leave_statistics(employee_id: int, year: int) -> dict:
        """
        Aggregates leave request statistics for a specific calendar year and employee.
        """
        total = LeaveRequest.query.filter(
            LeaveRequest.employee_id == employee_id,
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.is_active == True
        ).count()

        approved = LeaveRequest.query.filter(
            LeaveRequest.employee_id == employee_id,
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.status == "Approved",
            LeaveRequest.is_active == True
        ).count()

        rejected = LeaveRequest.query.filter(
            LeaveRequest.employee_id == employee_id,
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.status == "Rejected",
            LeaveRequest.is_active == True
        ).count()

        cancelled = LeaveRequest.query.filter(
            LeaveRequest.employee_id == employee_id,
            extract("year", LeaveRequest.start_date) == year,
            LeaveRequest.status == "Cancelled",
            LeaveRequest.is_active == True
        ).count()

        return {
            "total_requests": total,
            "approved": approved,
            "rejected": rejected,
            "cancelled": cancelled
        }

