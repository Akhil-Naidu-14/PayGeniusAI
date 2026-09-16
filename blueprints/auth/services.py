import logging
from sqlalchemy.exc import IntegrityError
from extensions import db
from models.user import User
from models.role import Role
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger("app")


class AuthService:
    """
    AuthService encapsulates all authentication and user provisioning business logic.
    Decoupled from request contexts and routes.
    """
    
    @staticmethod
    def authenticate_user(identifier, password):
        """
        Attempts to authenticate a user using username or email.
        Validates account activity flags, role presence/activity, and password hashes.
        
        Returns:
            (User, None) on success.
            (None, error_message) on failure.
        """
        if not identifier or not password:
            return None, "Invalid username/email or password."

        # Normalize the identifier by trimming and lowercasing
        normalized_id = identifier.strip().lower()
        
        # Query case-insensitively using func.lower
        user = User.query.filter(
            (db.func.lower(User.username) == normalized_id) | 
            (db.func.lower(User.email) == normalized_id)
        ).first()
        
        if not user:
            return None, "Invalid username/email or password."
            
        # Verify account active status
        if not user.is_active:
            return None, "Invalid username/email or password."
            
        # Verify role exists and is active
        if not user.role or not user.role.is_active:
            return None, "Invalid username/email or password."
            
        # Verify password hash
        if not check_password_hash(user.password_hash, password):
            return None, "Invalid username/email or password."
            
        return user, None

    @staticmethod
    def is_username_taken(username):
        """Checks if a username already exists in the system (case-insensitive)."""
        if not username:
            return False
        return User.query.filter(
            db.func.lower(User.username) == username.strip().lower()
        ).first() is not None

    @staticmethod
    def is_email_taken(email):
        """Checks if an email already exists in the system (case-insensitive)."""
        if not email:
            return False
        return User.query.filter(
            db.func.lower(User.email) == email.strip().lower()
        ).first() is not None

    @staticmethod
    def create_user_by_admin(username, email, password, role_id, employee_id=None):
        """
        Registers a new user inside the database with securely hashed credentials.
        Validates duplicate attributes, role status, and optional employee linking constraints.
        Uses transaction safety, rolls back on IntegrityError, and raises clean ValueErrors.
        """
        if not username or not email or not password or not role_id:
            raise ValueError("All fields are required.")

        clean_username = username.strip()
        clean_email = email.strip().lower()

        # 1. Validation check for duplicate username
        if AuthService.is_username_taken(clean_username):
            raise ValueError("Username is already in use.")

        # 2. Validation check for duplicate email
        if AuthService.is_email_taken(clean_email):
            raise ValueError("Email address is already in use.")

        # 3. Validate assigned role exists and is active
        role = db.session.get(Role, role_id)
        if not role:
            raise ValueError("Selected role does not exist.")

        if not role.is_active:
            raise ValueError("Selected role is inactive.")

        # 4. Validate optional linked employee
        if employee_id:
            from models.employee import Employee
            emp = db.session.get(Employee, employee_id)
            if not emp:
                raise ValueError("Selected employee does not exist.")
            if not emp.is_active:
                raise ValueError("Selected employee is inactive.")
            
            # Check if this employee is already linked to another active User
            already_linked = User.query.filter_by(employee_id=employee_id).first()
            if already_linked:
                raise ValueError("Selected employee is already linked to another user account.")

        # Create user database record
        new_user = User(
            username=clean_username,
            email=clean_email,
            password_hash=generate_password_hash(password),
            role_id=role_id,
            employee_id=employee_id
        )

        try:
            db.session.add(new_user)
            db.session.commit()
            return new_user
        except IntegrityError:
            db.session.rollback()
            raise ValueError("Database constraint conflict: Username, Email, or linked Employee already exists.")
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def get_roles_choices():
        """
        Retrieves all active database Role options formatted as SelectField choices.
        Returns list of tuples: (id, name).
        """
        try:
            # Only return active roles for selection
            roles = Role.query.filter_by(is_active=True).all()
            return [(role.id, role.name) for role in roles]
        except Exception:
            return []

    @staticmethod
    def _validate_password_strength(password, user, check_reuse=True):
        """
        Stateless helper to validate password complexity and user similarity constraints.
        Returns:
            (True, None) on success.
            (False, ERROR_CODE) on validation failures.
        """
        # Similarity checks
        if password == user.username:
            return False, "USERNAME_SIMILAR"

        email_local = user.email.split("@")[0]
        if password == email_local:
            return False, "EMAIL_SIMILAR"

        import re
        if len(password) < 8:
            return False, "WEAK_PASSWORD"
        if not re.search(r"[A-Z]", password):
            return False, "WEAK_PASSWORD"
        if not re.search(r"[a-z]", password):
            return False, "WEAK_PASSWORD"
        if not re.search(r"\d", password):
            return False, "WEAK_PASSWORD"

        # Reuse check
        if check_reuse and check_password_hash(user.password_hash, password):
            return False, "PASSWORD_REUSE"

        return True, None


    @staticmethod
    def change_password(user_id, current_password, new_password):
        """
        Updates the password for the current logged-in user.
        """
        user = db.session.get(User, user_id)
        if not user:
            logger.warning(
                "PASSWORD_CHANGE_FAILURE",
                extra={"user_id": user_id, "reason": "user_not_found"}
            )
            return False, "USER_NOT_FOUND"

        # Verify current password
        if not check_password_hash(user.password_hash, current_password):
            logger.warning(
                "PASSWORD_CHANGE_FAILURE",
                extra={"user_id": user_id, "reason": "incorrect_current_password"}
            )
            return False, "INCORRECT_PASSWORD"

        # Validate strength and constraints
        is_valid, err_code = AuthService._validate_password_strength(new_password, user, check_reuse=True)
        if not is_valid:
            logger.warning(
                "PASSWORD_CHANGE_FAILURE",
                extra={"user_id": user_id, "reason": err_code}
            )
            return False, err_code

        try:
            try:
                db.session.commit()
            except Exception:
                pass
            with db.session.begin():
                user_to_update = db.session.get(User, user_id)
                user_to_update.password_hash = generate_password_hash(new_password)
            logger.info(
                "PASSWORD_CHANGE_SUCCESS",
                extra={"user_id": user_id, "action": "self_change"}
            )
            return True, "SUCCESS"
        except Exception as e:
            logger.warning(
                "PASSWORD_CHANGE_FAILURE",
                extra={"user_id": user_id, "reason": f"db_error: {str(e)}"}
            )
            return False, "DATABASE_ERROR"

    @staticmethod
    def reset_user_password(target_user_id, new_password):
        """
        Resets the password for a target user (Admin action).
        """
        target_user = db.session.get(User, target_user_id)
        if not target_user or not target_user.is_active:
            logger.warning(
                "PASSWORD_RESET_FAILURE",
                extra={"target_user_id": target_user_id, "reason": "not_found_or_inactive"}
            )
            return False, "NOT_FOUND_OR_INACTIVE"

        # Validate strength and similarity
        is_valid, err_code = AuthService._validate_password_strength(new_password, target_user, check_reuse=False)
        if not is_valid:
            logger.warning(
                "PASSWORD_RESET_FAILURE",
                extra={"target_user_id": target_user_id, "reason": err_code}
            )
            return False, err_code

        try:
            try:
                db.session.commit()
            except Exception:
                pass
            with db.session.begin():
                user_to_update = db.session.get(User, target_user_id)
                user_to_update.password_hash = generate_password_hash(new_password)
            logger.info(
                "PASSWORD_RESET_SUCCESS",
                extra={"target_user_id": target_user_id}
            )
            return True, "SUCCESS"
        except Exception as e:
            logger.warning(
                "PASSWORD_RESET_FAILURE",
                extra={"target_user_id": target_user_id, "reason": f"db_error: {str(e)}"}
            )
            return False, "DATABASE_ERROR"






