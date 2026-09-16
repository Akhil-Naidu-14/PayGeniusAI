from flask import Blueprint

payroll_bp = Blueprint("payroll", __name__, template_folder="../../templates")

from blueprints.payroll import routes
