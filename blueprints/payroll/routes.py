from datetime import datetime
from decimal import Decimal
from flask import jsonify, request, abort, send_file, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from blueprints.payroll import payroll_bp
from blueprints.payroll.services import PayrollService
from blueprints.auth.decorators import roles_required
from models.role import RoleType
from models.employee import Employee
from models.payroll import Payroll
from models.department import Department
from utils.payslip_generator import generate_payslip_pdf
from extensions import db

def _resolve_employee_id() -> int | None:
    """Helper to map current login user to their active Employee ID."""
    emp = Employee.query.filter_by(email=current_user.email, is_active=True).first()
    return emp.id if emp else None

def _payroll_to_dict(p) -> dict:
    """Serializes a Payroll record to a JSON-safe dictionary."""
    return {
        "id": p.id,
        "employee_id": p.employee_id,
        "month": p.month,
        "year": p.year,
        "basic_salary": str(p.basic_salary),
        "hra": str(p.hra),
        "medical_allowance": str(p.medical_allowance),
        "travel_allowance": str(p.travel_allowance),
        "special_allowance": str(p.special_allowance),
        "bonus": str(p.bonus),
        "incentive": str(p.incentive),
        "overtime_pay": str(p.overtime_pay),
        "gross_salary": str(p.gross_salary),
        "provident_fund": str(p.provident_fund),
        "professional_tax": str(p.professional_tax),
        "income_tax": str(p.income_tax),
        "loan_deduction": str(p.loan_deduction),
        "insurance_deduction": str(p.insurance_deduction),
        "total_deductions": str(p.total_deductions),
        "net_salary": str(p.net_salary),
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None
    }

# ===========================================================================
# 1. Generate Payroll (HR/Admin only)
# ===========================================================================
@payroll_bp.route("/generate/<int:employee_id>/<int:month>/<int:year>", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def generate_payroll(employee_id: int, month: int, year: int):
    """
    Generates monthly payroll for a specific employee.
    Optional salary component overrides can be passed via JSON.
    """
    payload = request.get_json(silent=True) or {}

    # Gather custom allowances and deductions if provided
    kwargs = {}
    for field in [
        "hra", "medical_allowance", "travel_allowance", "special_allowance",
        "bonus", "incentive", "provident_fund", "professional_tax",
        "income_tax", "loan_deduction", "insurance_deduction"
    ]:
        if field in payload:
            try:
                kwargs[field] = Decimal(str(payload[field]))
            except (ValueError, TypeError):
                return jsonify({"success": False, "message": f"Invalid format for field {field}."}), 400

    res = PayrollService.generate_monthly_payroll(
        employee_id=employee_id,
        month=month,
        year=year,
        generated_by=current_user.id,
        apply_rule_defaults=True,
        **kwargs
    )

    if res["success"]:
        # Convert Decimals in result for JSON response
        return jsonify({
            "success": True,
            "message": "Payroll generated successfully.",
            "data": {
                "gross_salary": str(res["gross_salary"]),
                "net_salary": str(res["net_salary"]),
                "overtime_hours": str(res["overtime_hours"]),
                "unpaid_days": res["unpaid_days"]
            }
        }), 200

    return jsonify({"success": False, "message": res["message"]}), 400


# ===========================================================================
# 2. View Specific Payroll
# ===========================================================================
@payroll_bp.route("/<int:employee_id>/<int:month>/<int:year>", methods=["GET"])
@login_required
def view_payroll(employee_id: int, month: int, year: int):
    """
    Allows Employees to view their own payroll, and HR/Admin to view any.
    """
    # Authorization checks
    is_hr_or_admin = current_user.role.name in (RoleType.ADMIN, RoleType.HR)
    
    if not is_hr_or_admin:
        linked_emp_id = _resolve_employee_id()
        if linked_emp_id != employee_id:
            abort(403)  # Forbidden

    p = Payroll.query.filter_by(
        employee_id=employee_id,
        month=month,
        year=year,
        is_active=True
    ).first()

    if not p:
        return jsonify({"success": False, "message": "Payroll record not found."}), 404

    return jsonify({"success": True, "data": _payroll_to_dict(p)}), 200


# ===========================================================================
# 3. List Own Payroll History (Employee self-service)
# ===========================================================================
@payroll_bp.route("/my", methods=["GET"])
@login_required
def my_payroll_history():
    """
    Lists payroll history for the logged-in employee.
    """
    employee_id = _resolve_employee_id()
    if employee_id is None:
        return jsonify({"success": False, "message": "No linked employee record found."}), 403

    payrolls = Payroll.query.filter_by(
        employee_id=employee_id,
        is_active=True
    ).order_by(Payroll.year.desc(), Payroll.month.desc()).all()

    return jsonify({
        "success": True,
        "count": len(payrolls),
        "data": [_payroll_to_dict(p) for p in payrolls]
    }), 200


# ===========================================================================
# 4. List Month Payroll (HR/Admin only)
# ===========================================================================
@payroll_bp.route("/list/<int:month>/<int:year>", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def list_month_payroll(month: int, year: int):
    """
    Allows HR/Admin to list all payroll generated for a specific month and year.
    """
    payrolls = Payroll.query.filter_by(
        month=month,
        year=year,
        is_active=True
    ).order_by(Payroll.employee_id).all()

    return jsonify({
        "success": True,
        "month": month,
        "year": year,
        "count": len(payrolls),
        "data": [_payroll_to_dict(p) for p in payrolls]
    }), 200


# ===========================================================================
# 5. Download Payslip PDF
# ===========================================================================
@payroll_bp.route("/<int:payroll_id>/download", methods=["GET"])
@login_required
def download_payslip(payroll_id: int):
    """
    Generates and returns the payslip PDF for a payroll record.
    Security: Employees can only download their own payslip, HR/Admin can download any.
    """
    p = db.session.get(Payroll, payroll_id)
    if not p or not p.is_active:
        return jsonify({"success": False, "message": "Payroll record not found."}), 404

    # Resolve Employee
    emp = db.session.get(Employee, p.employee_id)
    if not emp or not emp.is_active:
        return jsonify({"success": False, "message": "Employee not found."}), 404

    # Authorization Check
    is_hr_or_admin = current_user.role.name in (RoleType.ADMIN, RoleType.HR)
    if not is_hr_or_admin:
        if current_user.email != emp.email:
            abort(403)

    # Fetch Department
    dept = db.session.get(Department, emp.department_id) if emp.department_id else None

    # Generate PDF
    pdf_stream = generate_payslip_pdf(p, emp, dept)

    return send_file(
        pdf_stream,
        download_name=f"payslip_{emp.employee_code}_{p.year}_{p.month:02d}.pdf",
        mimetype="application/pdf",
        as_attachment=True
    )


# ===========================================================================
# 6. Payroll UI (Admin/HR only)
# ===========================================================================
@payroll_bp.route("/ui", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def payroll_ui():
    """
    Renders the Payroll Management UI for Admin/HR users.
    Allows filtering by month and year, viewing generation status,
    and generating/downloading payslips.
    """
    now = datetime.now()
    try:
        month = int(request.args.get("month", now.month))
        year = int(request.args.get("year", now.year))
    except (ValueError, TypeError):
        month = now.month
        year = now.year

    if month < 1 or month > 12:
        month = now.month

    active_employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_code).all()

    existing_payrolls = Payroll.query.filter_by(
        month=month,
        year=year,
        is_active=True
    ).all()
    payroll_map = {p.employee_id: p for p in existing_payrolls}

    employees_data = []
    for emp in active_employees:
        p = payroll_map.get(emp.id)
        dept_name = emp.department.name if emp.department else "N/A"
        employees_data.append({
            "employee": emp,
            "department_name": dept_name,
            "payroll": p,
            "payroll_id": p.id if p else None,
            "status": "Generated" if p else "Not Generated"
        })

    return render_template(
        "payroll/index.html",
        month=month,
        year=year,
        employees_data=employees_data
    )


# ===========================================================================
# 7. Generate and Download Payslip (Admin/HR only)
# ===========================================================================
@payroll_bp.route("/ui/generate-download/<int:employee_id>/<int:month>/<int:year>", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def generate_and_download(employee_id: int, month: int, year: int):
    """
    Generates monthly payroll for an employee (if not already generated)
    and immediately redirects to the PDF download route.
    """
    res = PayrollService.generate_monthly_payroll(
        employee_id=employee_id,
        month=month,
        year=year,
        generated_by=current_user.id,
        apply_rule_defaults=True
    )

    p = Payroll.query.filter_by(
        employee_id=employee_id,
        month=month,
        year=year,
        is_active=True
    ).first()

    if p:
        download_url = url_for("payroll.download_payslip", payroll_id=p.id)
        return_url = url_for("payroll.payroll_ui", month=month, year=year)
        return render_template(
            "payroll/downloading.html",
            download_url=download_url,
            return_url=return_url
        )

    flash(res.get("message", "Failed to generate payroll record."), "danger")
    return redirect(url_for("payroll.payroll_ui", month=month, year=year))


# ===========================================================================
# 8. Archive Payroll Month (Admin/HR only)
# ===========================================================================
@payroll_bp.route("/ui/archive/<int:month>/<int:year>", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def archive_payroll_month(month: int, year: int):
    """
    Soft-deletes all generated payroll records for the specified month and year,
    allowing HR/Admin to regenerate them cleanly.
    """
    payrolls = Payroll.query.filter_by(month=month, year=year, is_active=True).all()
    count = len(payrolls)
    for p in payrolls:
        p.is_active = False

    db.session.commit()
    flash(f"Archived {count} payroll(s) for {month}/{year}.", "warning")
    return redirect(url_for("payroll.payroll_ui", month=month, year=year))
