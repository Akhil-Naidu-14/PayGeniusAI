from flask import Blueprint

attendance_upload_bp = Blueprint(
    "attendance_upload",
    __name__,
    template_folder="../../templates"
)

from blueprints.attendance_upload import routes
