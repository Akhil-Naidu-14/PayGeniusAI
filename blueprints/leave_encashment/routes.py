from flask import jsonify, request, abort
from flask_login import login_required, current_user

from blueprints.leave_encashment import leave_encashment_bp
from blueprints.leave_encashment.services import LeaveEncashmentService
from blueprints.auth.decorators import roles_required
from models.role import RoleType
from models.employee import Employee
from models.leave_encashment import LeaveEncashment

@leave_encashment_bp.route("/encashment/apply", methods=["POST"])
@login_required
def apply_encashment():
    """
    Endpoint for standard employees to request converting unused leave days to cash.
    """
    emp = Employee.query.filter_by(email=current_user.email, is_active=True).first()
    if not emp:
        return jsonify({"success": False, "message": "Employee details not found for current user."}), 404

    # Extract JSON or form fields
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    leave_type_id = data.get("leave_type_id")
    year = data.get("year")
    days_requested = data.get("days_requested")

    if not leave_type_id or not year or not days_requested:
        return jsonify({"success": False, "message": "Missing required fields."}), 400

    try:
        leave_type_id = int(leave_type_id)
        year = int(year)
        days_requested = int(days_requested)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid input parameters."}), 400

    res = LeaveEncashmentService.apply_encashment(
        employee_id=emp.id,
        leave_type_id=leave_type_id,
        year=year,
        days_requested=days_requested
    )

    status_code = 200 if res["success"] else 400
    return jsonify(res), status_code

@leave_encashment_bp.route("/encashment/<int:id>/approve", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def approve_encashment(id: int):
    """
    HR/Admin endpoint to approve a pending leave encashment request.
    """
    res = LeaveEncashmentService.approve_encashment(encashment_id=id, approver_id=current_user.id)
    status_code = 200 if res["success"] else 400
    return jsonify(res), status_code

@leave_encashment_bp.route("/encashment/<int:id>/reject", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def reject_encashment(id: int):
    """
    HR/Admin endpoint to reject a pending leave encashment request.
    """
    res = LeaveEncashmentService.reject_encashment(encashment_id=id, approver_id=current_user.id)
    status_code = 200 if res["success"] else 400
    return jsonify(res), status_code

@leave_encashment_bp.route("/encashment/all", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def list_encashments():
    """
    HR/Admin endpoint to retrieve all leave encashment records.
    """
    requests = LeaveEncashment.query.filter_by(is_active=True).all()
    data = [{
        "id": req.id,
        "employee_id": req.employee_id,
        "leave_type_id": req.leave_type_id,
        "year": req.year,
        "days_requested": req.days_requested,
        "amount_per_day": str(req.amount_per_day),
        "total_amount": str(req.total_amount),
        "status": req.status,
        "approved_by": req.approved_by,
        "approved_at": req.approved_at.isoformat() if req.approved_at else None
    } for req in requests]

    return jsonify({"success": True, "data": data}), 200
