from flask import Blueprint

attendance_bp = Blueprint("attendance", __name__, template_folder="../../templates")

from blueprints.attendance import routes
