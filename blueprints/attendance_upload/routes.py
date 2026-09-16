from flask import jsonify, request, abort, render_template
from flask_login import login_required

from blueprints.attendance_upload import attendance_upload_bp
from blueprints.attendance_upload.forms import AttendanceUploadForm
from blueprints.attendance_upload.services import AttendanceUploadService
from blueprints.auth.decorators import roles_required
from models.role import RoleType

@attendance_upload_bp.route("/attendance/upload", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def upload_attendance():
    """
    Endpoint for HR/Admin to upload bulk attendance records (.xlsx).
    Returns a JSON structured summary of processed records.
    """
    form = AttendanceUploadForm()
    
    # Check if a file is uploaded
    if "excel_file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded."}), 400

    file = request.files["excel_file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected."}), 400

    # Verify file extension is .xlsx
    if not file.filename.endswith(".xlsx"):
        return jsonify({"success": False, "message": "Only Excel (.xlsx) files are supported."}), 400

    # Call upload service using the file stream
    summary = AttendanceUploadService.upload_attendance_excel(file.stream)

    if summary["success"]:
        return jsonify({
            "success": True,
            "records_processed": summary["records_processed"],
            "records_updated": summary["records_updated"],
            "records_failed": summary["records_failed"],
            "errors": summary["errors"]
        }), 200

    return jsonify({
        "success": False,
        "message": summary.get("message", "An error occurred during file upload."),
        "records_processed": 0,
        "records_updated": 0,
        "records_failed": summary.get("records_failed", 0)
    }), 400


@attendance_upload_bp.route("/attendance/upload-ui", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def upload_attendance_ui():
    """
    UI Route for HR/Admin to upload bulk attendance records (.xlsx).
    Renders an HTML form on GET and processes file upload on POST,
    reusing AttendanceUploadService.upload_attendance_excel.
    """
    form = AttendanceUploadForm()
    summary = None
    error_message = None

    if request.method == "POST":
        if "excel_file" not in request.files or request.files["excel_file"].filename == "":
            error_message = "Please select a file to upload."
        else:
            file = request.files["excel_file"]
            if not file.filename.endswith(".xlsx"):
                error_message = "Only Excel (.xlsx) files are supported."
            else:
                summary = AttendanceUploadService.upload_attendance_excel(file.stream)
                if not summary.get("success"):
                    error_message = summary.get("message", "An error occurred during file upload.")
                else:
                    summary["records_created"] = summary.get("records_processed", 0) - summary.get("records_updated", 0)

    return render_template(
        "attendance/upload.html",
        form=form,
        summary=summary,
        error_message=error_message
    )

