from flask import Blueprint

leave_encashment_bp = Blueprint("leave_encashment", __name__)

from blueprints.leave_encashment import routes
