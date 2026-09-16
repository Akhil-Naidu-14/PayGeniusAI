from urllib.parse import urlsplit
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_user, logout_user, login_required, current_user

from blueprints.auth import auth_bp
from blueprints.auth.forms import LoginForm, UserCreateForm, ChangePasswordForm, ResetPasswordForm
from blueprints.auth.services import AuthService
from blueprints.auth.decorators import roles_required
from models.role import RoleType

def is_safe_redirect(next_page):
    """
    Validates redirect targets to prevent Open Redirect attacks.
    Only allows relative local paths starting with a single '/'.
    """
    if not next_page:
        return False
    parsed = urlsplit(next_page)
    # Check that there is no netloc, no scheme, and it starts with a single '/'
    return parsed.scheme == "" and parsed.netloc == "" and next_page.startswith("/") and not next_page.startswith("//")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Renders the secure user login panel and processes inputs."""
    if current_user.is_authenticated:
        return redirect(url_for("analytics.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        # Authenticate credentials using AuthService
        user, error = AuthService.authenticate_user(
            form.username_or_email.data, 
            form.password.data
        )
        
        if error:
            flash(error, "danger")
            return render_template("auth/login.html", form=form)

        # Login session validation
        login_user(user, remember=form.remember_me.data)
        flash("You have successfully logged in.", "success")
        
        # Check next redirect query param to prevent open redirect vulnerabilities
        next_page = request.args.get("next")
        if not is_safe_redirect(next_page):
            next_page = url_for("analytics.dashboard")
            
        return redirect(next_page)

    return render_template("auth/login.html", form=form)



@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """
    Resets user session and redirects to the login screen.
    POST-only route to secure session terminations from CSRF GET requests.
    """
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/admin/create-user", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN)
def create_user():
    """
    Renders administrative user registration panel.
    Protected by admin authorization role constraints.
    """
    from extensions import db
    from models.user import User
    from models.employee import Employee
    
    form = UserCreateForm()
    
    # Populate dynamic role options prior to validation check
    form.role_id.choices = AuthService.get_roles_choices()

    # Populate dynamic employee choices: active employees that are not already linked to another User
    linked_emp_ids = db.session.scalars(
        db.select(User.employee_id).where(User.employee_id.is_not(None))
    ).all()
    
    emp_query = db.select(Employee).where(Employee.is_active == True)
    if linked_emp_ids:
        emp_query = emp_query.where(Employee.id.not_in(linked_emp_ids))
    
    unlinked_employees = db.session.scalars(
        emp_query.order_by(Employee.last_name, Employee.first_name)
    ).all()
    
    form.employee_id.choices = [(0, "No employee / Not linked")] + [
        (emp.id, f"{emp.first_name} {emp.last_name} ({emp.employee_code})")
        for emp in unlinked_employees
    ]
    
    # Query all active users for listing
    users = db.session.scalars(db.select(User).filter_by(is_active=True).order_by(User.username)).all()

    if form.validate_on_submit():
        try:
            selected_emp_id = form.employee_id.data if form.employee_id.data != 0 else None
            # Perform user creation via AuthService, which validates duplicates internally
            AuthService.create_user_by_admin(
                username=form.username.data,
                email=form.email.data,
                password=form.password.data,
                role_id=form.role_id.data,
                employee_id=selected_emp_id
            )
            flash(f"User account '{form.username.data}' successfully created.", "success")
            return redirect(url_for("auth.create_user"))
        except ValueError as e:
            # Catch domain exception and display to user
            flash(str(e), "danger")
            return render_template("auth/create_user.html", form=form, users=users)

    return render_template("auth/create_user.html", form=form, users=users)


PASSWORD_ERROR_MESSAGES = {
    "USER_NOT_FOUND": "The requested user account was not found or is inactive.",
    "INCORRECT_PASSWORD": "The current password you entered is incorrect.",
    "WEAK_PASSWORD": "Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, and one digit.",
    "PASSWORD_REUSE": "New password cannot be the same as your current password.",
    "USERNAME_SIMILAR": "New password cannot be equal to your username.",
    "EMAIL_SIMILAR": "New password cannot be equal to your email address local part.",
    "DATABASE_ERROR": "A database error occurred. Please try again."
}


@auth_bp.route("/auth/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Handles self-initiated password changes for authenticated users."""
    from flask import session
    form = ChangePasswordForm()
    
    if form.validate_on_submit():
        success, status_code = AuthService.change_password(
            user_id=current_user.id,
            current_password=form.current_password.data,
            new_password=form.new_password.data
        )
        if success:
            logout_user()
            session.clear()
            flash("Password changed successfully. Please log in again.", "success")
            return redirect(url_for("auth.login"))
        else:
            flash_msg = PASSWORD_ERROR_MESSAGES.get(status_code, "An error occurred during password change.")
            flash(flash_msg, "danger")

            
    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/auth/reset-password/<int:user_id>", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN)
def reset_password(user_id):
    """Handles administrative password resets for other accounts."""
    if current_user.id == user_id:
        abort(403)
        
    form = ResetPasswordForm()
    
    if form.validate_on_submit():
        success, status_code = AuthService.reset_user_password(
            target_user_id=user_id,
            new_password=form.new_password.data
        )
        if success or status_code == "NOT_FOUND_OR_INACTIVE":
            flash("Password reset request processed.", "success")
            # Clear form on success to avoid rendering values
            form = ResetPasswordForm(formdata=None)
            return render_template("auth/reset_password.html", form=form), 200
        else:
            flash_msg = PASSWORD_ERROR_MESSAGES.get(status_code, "An error occurred during password reset.")
            flash(flash_msg, "danger")
            return render_template("auth/reset_password.html", form=form), 200
            
    return render_template("auth/reset_password.html", form=form), 200

