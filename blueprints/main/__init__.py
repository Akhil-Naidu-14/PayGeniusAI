from flask import Blueprint

main_bp = Blueprint("main", __name__)

# Import routes to register them with the blueprint
from blueprints.main import routes
