from flask import Blueprint

# Initialize the authentication blueprint namespace
auth_bp = Blueprint("auth", __name__)

# Register routes to the blueprint context
from blueprints.auth import routes
