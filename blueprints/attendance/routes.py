"""
Attendance Routes

Role matrix:
    Employees      → check-in, check-out, view own attendance / monthly summary
    HR + Admin     → view all, manual mark, override, view any employee summary
"""

from datetime import date

from flask import jsonify, request, abort
from flask_login import login_required, current_user

from blueprints.attendance import attendance_bp
from blueprints.attendance.services import AttendanceService
from blueprints.auth.decorators import roles_required
from models.role import RoleType

# ---------------------------------------------------------------------------
# Status-code → user-facing message map
# ---------------------------------------------------------------------------
_CHECK_IN_MESSAGES = {
    "SUCCESS":            "Checked in successfully.",
    "NOT_FOUND":          "Employee record not found or inactive.",
    "ALREADY_CHECKED_IN": "You have already checked in today.",
    "RECORD_DELETED":     "Attendance record for today has been removed. Contact HR.",
    "DATABASE_ERROR":     "An internal error occurred. Please try again.",
}

_CHECK_OUT_MESSAGES = {
    "SUCCESS":              "Checked out successfully.",
    "NOT_FOUND":            "Employee record not found or inactive.",
    "NO_CHECK_IN":          "No check-in record found for today.",
    "ALREADY_CHECKED_OUT":  "You have already checked out today.",
    "RECORD_DELETED":       "Attendance record for today has been removed. Contact HR.",
    "DATABASE_ERROR":       "An internal error occurred. Please try again.",
}

_MARK_MESSAGES = {
    "SUCCESS":        "Attendance marked successfully.",
    "NOT_FOUND":      "Employee not found or inactive.",
    "INVALID_STATUS": "Invalid attendance status.",
    "INVALID_TIMES":  "Check-out time must be after check-in time.",
    "DATABASE_ERROR": "An internal error occurred. Please try again.",
}

_SOFT_DELETE_MESSAGES = {
    "SUCCESS":        "Attendance record deleted.",
    "NOT_FOUND":      "Attendance record not found.",
    "DATABASE_ERROR": "An internal error occurred. Please try again.",
}


def _attendance_to_dict(record) -> dict:
    """Serialises an Attendance ORM object to a JSON-safe dict."""
    return {
        "id":                   record.id,
        "employee_id":          record.employee_id,
        "date":                 str(record.date),
        "check_in":             record.check_in.isoformat() if record.check_in else None,
        "check_out":            record.check_out.isoformat() if record.check_out else None,
        "working_hours":        str(record.working_hours)  if record.working_hours  is not None else None,
        "overtime_hours":       str(record.overtime_hours) if record.overtime_hours is not None else None,
        "late_minutes":         record.late_minutes,
        "early_leave_minutes":  record.early_leave_minutes,
        "status":               record.status,
        "is_active":            record.is_active,
    }


# ===========================================================================
# 1. Employee: Check-In
# ===========================================================================
@attendance_bp.route("/attendance/check-in", methods=["POST"])
@login_required
def check_in():
    """
    Employee self check-in.
    The employee_id is derived from the authenticated user's linked employee record.
    """
    employee_id = _resolve_employee_id()
    if employee_id is None:
        return jsonify({"success": False, "message": "No linked employee record found."}), 403

    success, code, record = AttendanceService.check_in(employee_id)
    message = _CHECK_IN_MESSAGES.get(code, "Unknown error.")

    if success:
        return jsonify({"success": True, "message": message, "data": _attendance_to_dict(record)}), 200

    status_http = 400 if code in ("ALREADY_CHECKED_IN", "RECORD_DELETED") else 422
    return jsonify({"success": False, "message": message, "code": code}), status_http


# ===========================================================================
# 2. Employee: Check-Out
# ===========================================================================
@attendance_bp.route("/attendance/check-out", methods=["POST"])
@login_required
def check_out():
    """
    Employee self check-out. Triggers automatic field computation.
    """
    employee_id = _resolve_employee_id()
    if employee_id is None:
        return jsonify({"success": False, "message": "No linked employee record found."}), 403

    success, code, record = AttendanceService.check_out(employee_id)
    message = _CHECK_OUT_MESSAGES.get(code, "Unknown error.")

    if success:
        return jsonify({"success": True, "message": message, "data": _attendance_to_dict(record)}), 200

    status_http = 400 if code in ("NO_CHECK_IN", "ALREADY_CHECKED_OUT", "RECORD_DELETED") else 422
    return jsonify({"success": False, "message": message, "code": code}), status_http


# ===========================================================================
# 3. Employee: View own attendance for a date
# ===========================================================================
@attendance_bp.route("/attendance/my/<string:target_date>", methods=["GET"])
@login_required
def my_attendance_for_date(target_date: str):
    """
    Employee view of their own attendance for a specific date (YYYY-MM-DD).
    """
    employee_id = _resolve_employee_id()
    if employee_id is None:
        return jsonify({"success": False, "message": "No linked employee record found."}), 403

    parsed = _parse_date(target_date)
    if parsed is None:
        return jsonify({"success": False, "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    record = AttendanceService.get_employee_attendance(employee_id, parsed)
    if not record:
        return jsonify({"success": False, "message": "No attendance record found for this date."}), 404

    return jsonify({"success": True, "data": _attendance_to_dict(record)}), 200


# ===========================================================================
# 4. Employee: Monthly summary (own)
# ===========================================================================
@attendance_bp.route("/attendance/my/summary/<int:year>/<int:month>", methods=["GET"])
@login_required
def my_monthly_summary(year: int, month: int):
    """
    Employee view of their own monthly attendance summary.
    """
    employee_id = _resolve_employee_id()
    if employee_id is None:
        return jsonify({"success": False, "message": "No linked employee record found."}), 403

    if not (1 <= month <= 12):
        return jsonify({"success": False, "message": "Month must be between 1 and 12."}), 400

    summary = AttendanceService.get_monthly_summary(employee_id, month, year)
    # Decimal values must be serialised to str for JSON
    summary["total_working_hours"]  = str(summary["total_working_hours"])
    summary["total_overtime_hours"] = str(summary["total_overtime_hours"])
    return jsonify({"success": True, "data": summary}), 200


# ===========================================================================
# 5. HR/Admin: View all attendance for a given date
# ===========================================================================
@attendance_bp.route("/attendance/all/<string:target_date>", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def all_attendance_for_date(target_date: str):
    """
    HR/Admin view of all employee attendance records for a specific date.
    """
    parsed = _parse_date(target_date)
    if parsed is None:
        return jsonify({"success": False, "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    records = AttendanceService.get_all_attendance_for_date(parsed)
    return jsonify({
        "success": True,
        "date": str(parsed),
        "count": len(records),
        "data": [_attendance_to_dict(r) for r in records],
    }), 200


# ===========================================================================
# 6. HR/Admin: View a specific employee's monthly summary
# ===========================================================================
@attendance_bp.route("/attendance/<int:employee_id>/summary/<int:year>/<int:month>", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def employee_monthly_summary(employee_id: int, year: int, month: int):
    """
    HR/Admin view of monthly attendance summary for any employee.
    """
    if not (1 <= month <= 12):
        return jsonify({"success": False, "message": "Month must be between 1 and 12."}), 400

    summary = AttendanceService.get_monthly_summary(employee_id, month, year)
    summary["total_working_hours"]  = str(summary["total_working_hours"])
    summary["total_overtime_hours"] = str(summary["total_overtime_hours"])
    return jsonify({"success": True, "data": summary}), 200


# ===========================================================================
# 7. HR/Admin: Manual attendance mark / override
# ===========================================================================
@attendance_bp.route("/attendance/mark", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def mark_attendance():
    """
    HR/Admin manual attendance mark or override.

    Expected JSON body:
    {
        "employee_id": int,
        "date":        "YYYY-MM-DD",
        "status":      "Present" | "Absent" | "Half Day" | "On Leave",
        "check_in":    "ISO-8601 datetime (optional)",
        "check_out":   "ISO-8601 datetime (optional)"
    }
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"success": False, "message": "JSON body required."}), 400

    employee_id = payload.get("employee_id")
    date_str    = payload.get("date")
    status      = payload.get("status")

    if not employee_id or not date_str or not status:
        return jsonify({"success": False, "message": "employee_id, date, and status are required."}), 400

    target_date = _parse_date(date_str)
    if target_date is None:
        return jsonify({"success": False, "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    check_in  = _parse_iso_datetime(payload.get("check_in"))
    check_out = _parse_iso_datetime(payload.get("check_out"))

    success, code, record = AttendanceService.mark_attendance(
        employee_id=int(employee_id),
        target_date=target_date,
        status=status,
        check_in=check_in,
        check_out=check_out,
    )
    message = _MARK_MESSAGES.get(code, "Unknown error.")

    if success:
        return jsonify({"success": True, "message": message, "data": _attendance_to_dict(record)}), 200

    status_http = 422 if code in ("NOT_FOUND", "INVALID_STATUS", "INVALID_TIMES") else 500
    return jsonify({"success": False, "message": message, "code": code}), status_http


# ===========================================================================
# 8. HR/Admin: Soft-delete an attendance record
# ===========================================================================
@attendance_bp.route("/attendance/<int:attendance_id>", methods=["DELETE"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def delete_attendance(attendance_id: int):
    """
    HR/Admin soft-deletes an attendance record (sets is_active=False).
    """
    success, code = AttendanceService.soft_delete_attendance(attendance_id)
    message = _SOFT_DELETE_MESSAGES.get(code, "Unknown error.")

    if success:
        return jsonify({"success": True, "message": message}), 200

    status_http = 404 if code == "NOT_FOUND" else 500
    return jsonify({"success": False, "message": message, "code": code}), status_http


# ===========================================================================
# Helpers
# ===========================================================================
def _resolve_employee_id() -> int | None:
    """
    Maps the currently authenticated user to their Employee record ID.
    The current schema links Users ↔ Employees via email.
    Returns None if no active employee record is found.
    """
    from extensions import db
    from models.employee import Employee
    emp = (
        Employee.query
        .filter_by(email=current_user.email, is_active=True)
        .first()
    )
    return emp.id if emp else None


def _parse_date(date_str: str) -> date | None:
    """Parses a YYYY-MM-DD string into a date object; returns None on failure."""
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _parse_iso_datetime(dt_str: str | None):
    """Parses an ISO-8601 datetime string; returns None on failure."""
    if not dt_str:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(dt_str)
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
