from flask import jsonify, abort
from flask_login import login_required, current_user

from blueprints.ai import ai_bp
from blueprints.ai.services import AIService
from blueprints.auth.decorators import roles_required
from models.role import RoleType
from models.payroll import Payroll

@ai_bp.route("/payroll/<int:employee_id>/<int:month>/<int:year>/analysis", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def payroll_analysis(employee_id: int, month: int, year: int):
    """
    Exposes payroll analysis to HR and Administrator users.
    Returns JSON formatted summary, recommendations, and risk level.
    """
    # 1. Ensure payroll exists
    payroll = Payroll.query.filter_by(
        employee_id=employee_id,
        month=month,
        year=year,
        is_active=True
    ).first()

    if not payroll:
        return jsonify({"success": False, "message": "Payroll record not found."}), 404

    # 2 & 3. Generate analysis (which runs anomaly detection and AIService under the hood)
    res = AIService.generate_payroll_analysis(
        employee_id=employee_id,
        month=month,
        year=year,
        user_id=current_user.id
    )

    return jsonify({
        "success": True,
        "data": res
    }), 200
