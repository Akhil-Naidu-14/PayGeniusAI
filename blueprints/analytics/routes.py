from datetime import date
from typing import Optional
from flask import jsonify, request, render_template, abort
from flask_login import login_required, current_user

from extensions import db
from blueprints.analytics import analytics_bp
from blueprints.analytics.services import AnalyticsService
from blueprints.analytics.prediction_service import AttendancePredictionService
from blueprints.ai.services import AIService
from blueprints.auth.decorators import roles_required
from models.role import RoleType
from models.employee import Employee

def _resolve_employee_id_for_current_user() -> Optional[int]:
    """
    Resolves the Employee ID for current_user.
    Checks explicit foreign key link current_user.employee_id first,
    falling back to matching Employee by active email.
    """
    if getattr(current_user, "employee_id", None):
        emp = db.session.get(Employee, current_user.employee_id)
        if emp and emp.is_active:
            return emp.id
    emp = Employee.query.filter_by(email=current_user.email, is_active=True).first()
    return emp.id if emp else None

@analytics_bp.route("/analytics/payroll-trend", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def payroll_trend():
    last_n = request.args.get("last_n_months", default=6, type=int)
    res = AnalyticsService.get_payroll_trend(last_n_months=last_n)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/department-salary", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def department_salary():
    res = AnalyticsService.get_department_salary_distribution()
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/attendance-trend", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def attendance_trend():
    last_n = request.args.get("last_n_months", default=6, type=int)
    res = AnalyticsService.get_attendance_trend(last_n_months=last_n)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/leave-stats/<int:year>", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def leave_stats(year: int):
    res = AnalyticsService.get_leave_statistics(year=year)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/compliance-risk/<int:month>/<int:year>", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def compliance_risk(month: int, year: int):
    res = AnalyticsService.get_compliance_risk_summary(month=month, year=year)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/personal/payroll-trend", methods=["GET"])
@login_required
def personal_payroll_trend():
    emp_id = _resolve_employee_id_for_current_user()
    if not emp_id:
        return jsonify({"success": False, "message": "Employee details not found."}), 404
    last_n = request.args.get("last_n_months", default=6, type=int)
    res = AnalyticsService.get_personal_payroll_trend(employee_id=emp_id, last_n_months=last_n)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/personal/attendance-trend", methods=["GET"])
@login_required
def personal_attendance_trend():
    emp_id = _resolve_employee_id_for_current_user()
    if not emp_id:
        return jsonify({"success": False, "message": "Employee details not found."}), 404
    last_n = request.args.get("last_n_months", default=6, type=int)
    res = AnalyticsService.get_personal_attendance_trend(employee_id=emp_id, last_n_months=last_n)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/personal/leave-stats/<int:year>", methods=["GET"])
@login_required
def personal_leave_stats(year: int):
    emp_id = _resolve_employee_id_for_current_user()
    if not emp_id:
        return jsonify({"success": False, "message": "Employee details not found."}), 404
    res = AnalyticsService.get_personal_leave_statistics(employee_id=emp_id, year=year)
    return jsonify({"success": True, "data": res}), 200

@analytics_bp.route("/analytics/api/attendance-prediction/<int:employee_id>", methods=["GET"])
@login_required
def api_attendance_prediction(employee_id: int):
    """
    JSON API endpoint returning ML attendance predictions with strict User.employee_id RBAC enforcement.
    """
    is_admin = current_user.role and current_user.role.name in [RoleType.ADMIN, RoleType.HR]
    if not is_admin:
        if current_user.employee_id is None or current_user.employee_id != employee_id:
            return jsonify({"success": False, "message": "Unauthorized access to employee forecast."}), 403

    res = AttendancePredictionService.predict_next_month_attendance(employee_id)
    return jsonify(res), 200

@analytics_bp.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    """
    Renders the Reports & Analytics Dashboard.
    HR Managers and Administrators view the full organization-level dashboard with an AI executive summary and ML attendance forecasts.
    Standard Employees view a limited personal dashboard containing only their own metrics and personal ML attendance prediction.
    """
    is_admin = False
    if current_user.role and current_user.role.name in [RoleType.ADMIN, RoleType.HR]:
        is_admin = True

    exec_summary = None
    prediction_data = None

    if is_admin:
        today = date.today()
        exec_summary = AIService.generate_executive_summary(
            month=today.month,
            year=today.year,
            user_id=current_user.id
        )
        prediction_data = AttendancePredictionService.get_organization_prediction_summary()
    else:
        if current_user.employee_id:
            prediction_data = [AttendancePredictionService.predict_next_month_attendance(current_user.employee_id)]

    return render_template(
        "analytics/dashboard.html",
        is_admin=is_admin,
        executive_summary=exec_summary,
        prediction_data=prediction_data,
        current_year=date.today().year,
        current_month=date.today().month
    )
