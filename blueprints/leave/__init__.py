from flask import Blueprint

leave_bp = Blueprint("leave", __name__, template_folder="../../templates")

from blueprints.leave import routes
