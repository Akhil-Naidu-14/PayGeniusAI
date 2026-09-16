from functools import wraps
from flask import abort
from flask_login import current_user

def roles_required(*roles):
    """
    Decorator to restrict route access to specific user roles.
    Checks user.role.name against the list of authorized roles.
    Returns HTTP 403 if the user lacks permissions, or 401 if unauthenticated.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Enforce authentication check
            if not current_user.is_authenticated:
                abort(401)
                
            # Check user role mapping
            user_role = getattr(current_user, "role", None)
            if not user_role or user_role.name not in roles:
                # HTTP 403 Forbidden
                abort(403)
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
