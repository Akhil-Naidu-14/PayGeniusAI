from flask import Blueprint

ai_bp = Blueprint("ai", __name__)

from blueprints.ai import routes
