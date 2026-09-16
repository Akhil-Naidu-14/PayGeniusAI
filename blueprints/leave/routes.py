"""
Leave Management Routes

Role matrix:
    Employee   → apply, cancel own Pending, view own requests/balances
    HR + Admin → view all, approve, reject
"""

from datetime import date

from flask import flash, redirect, render_template, request, url_for, abort, jsonify
from flask_login import login_required, current_user

from blueprints.leave import leave_bp
from blueprints.leave.forms import ApplyLeaveForm, RejectLeaveForm, CancelLeaveForm
from blueprints.leave.services import LeaveService
from blueprints.auth.decorators import roles_required
from models.leave_type import LeaveType
from models.role import RoleType

# ---------------------------------------------------------------------------
# Status-code → user-facing flash message maps
# ---------------------------------------------------------------------------
_APPLY_MSG = {
    "SUCCESS":       "Your leave request has been submitted.",
    "NOT_FOUND":     "Employee or leave type not found.",
    "INVALID_DATES": "End date must be on or after start date.",
    "OVERLAP":       "You already have a Pending or Approved leave in this date range.",
    "NO_BALANCE":    "No leave balance found for this leave type and year.",
    "INSUFFICIENT":  "You do not have enough remaining leave days.",
    "DATABASE_ERROR":"An internal error occurred. Please try again.",
}
_APPROVE_MSG = {
    "SUCCESS":         "Leave request approved.",
    "NOT_FOUND":       "Leave request not found.",
    "ALREADY_ACTIONED":"This request has already been actioned.",
    "NO_BALANCE":      "Leave balance record not found for this employee.",
    "INSUFFICIENT":    "Insufficient leave balance.",
    "DATABASE_ERROR":  "An internal error occurred.",
}
_REJECT_MSG = {
    "SUCCESS":         "Leave request rejected.",
    "NOT_FOUND":       "Leave request not found.",
    "ALREADY_ACTIONED":"This request has already been actioned.",
    "DATABASE_ERROR":  "An internal error occurred.",
}
_CANCEL_MSG = {
    "SUCCESS":       "Your leave request has been cancelled.",
    "NOT_FOUND":     "Leave request not found.",
    "FORBIDDEN":     "You are not authorised to cancel this request.",
    "NOT_PENDING":   "Only Pending requests may be cancelled.",
    "DATABASE_ERROR":"An internal error occurred.",
}


def _resolve_employee_id():
    """Maps the current user to their Employee record via email."""
    from extensions import db
    from models.employee import Employee
    emp = Employee.query.filter_by(email=current_user.email, is_active=True).first()
    return emp.id if emp else None


# ===========================================================================
# Employee: Apply for leave
# ===========================================================================
@leave_bp.route("/leave/apply", methods=["GET", "POST"])
@login_required
def apply_leave():
    """Employee submits a new leave request."""
    employee_id = _resolve_employee_id()
    if employee_id is None:
        flash("No linked employee record found. Contact HR.", "danger")
        return redirect(url_for("main.index"))

    form = ApplyLeaveForm()
    active_types = LeaveType.query.filter_by(is_active=True).all()
    form.leave_type_id.choices = [(lt.id, lt.name) for lt in active_types]

    if form.validate_on_submit():
        success, code, _ = LeaveService.apply_leave(
            employee_id=employee_id,
            leave_type_id=form.leave_type_id.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            reason=form.reason.data,
        )
        flash(_APPLY_MSG.get(code, "Unknown error."), "success" if success else "danger")
        if success:
            return redirect(url_for("leave.my_requests"))

    return render_template("leave/apply.html", form=form, title="Apply for Leave")


# ===========================================================================
# Employee: View own requests
# ===========================================================================
@leave_bp.route("/leave/my", methods=["GET"])
@login_required
def my_requests():
    """Employee views their own leave request history."""
    employee_id = _resolve_employee_id()
    if employee_id is None:
        flash("No linked employee record found. Contact HR.", "danger")
        return redirect(url_for("main.index"))

    requests_list = LeaveService.list_employee_requests(employee_id)
    year = date.today().year
    balances = LeaveService.list_employee_balances(employee_id, year)
    return render_template(
        "leave/my_requests.html",
        requests=requests_list,
        balances=balances,
        year=year,
        title="My Leave Requests",
    )


# ===========================================================================
# Employee: Cancel own Pending request
# ===========================================================================
@leave_bp.route("/leave/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel_leave(request_id: int):
    """Employee cancels their own Pending leave request."""
    employee_id = _resolve_employee_id()
    if employee_id is None:
        abort(403)

    success, code, _ = LeaveService.cancel_leave(request_id, employee_id)
    flash(_CANCEL_MSG.get(code, "Unknown error."), "success" if success else "danger")
    return redirect(url_for("leave.my_requests"))


# ===========================================================================
# HR/Admin: View all leave requests
# ===========================================================================
@leave_bp.route("/leave/all", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def all_requests():
    """HR/Admin views all leave requests with optional status filter."""
    status_filter = request.args.get("status", "")
    requests_list = LeaveService.list_all_requests(
        status=status_filter if status_filter else None
    )
    from models.leave_request import LeaveRequestStatus
    return render_template(
        "leave/all_requests.html",
        requests=requests_list,
        status_filter=status_filter,
        statuses=LeaveRequestStatus.CHOICES,
        title="All Leave Requests",
    )


# ===========================================================================
# HR/Admin: Approve a leave request
# ===========================================================================
@leave_bp.route("/leave/<int:request_id>/approve", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def approve_leave(request_id: int):
    """HR/Admin approves a Pending leave request."""
    success, code, _ = LeaveService.approve_leave(request_id, current_user.id)
    flash(_APPROVE_MSG.get(code, "Unknown error."), "success" if success else "danger")
    return redirect(url_for("leave.all_requests"))


# ===========================================================================
# HR/Admin: Reject a leave request
# ===========================================================================
@leave_bp.route("/leave/<int:request_id>/reject", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def reject_leave(request_id: int):
    """HR/Admin rejects a Pending leave request."""
    success, code, _ = LeaveService.reject_leave(request_id, current_user.id)
    flash(_REJECT_MSG.get(code, "Unknown error."), "success" if success else "danger")
    return redirect(url_for("leave.all_requests"))
