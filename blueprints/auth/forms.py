from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SelectField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo

class LoginForm(FlaskForm):
    """WTForms schema for handling user login requests."""
    username_or_email = StringField(
        "Username or Email", 
        validators=[
            DataRequired(message="Username or Email is required."),
            Length(min=3, max=120, message="Identifier must be between 3 and 120 characters.")
        ]
    )
    password = PasswordField(
        "Password", 
        validators=[DataRequired(message="Password is required.")]
    )
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Log In")


class UserCreateForm(FlaskForm):
    """WTForms schema for handling user registration by an Administrator."""
    username = StringField(
        "Username", 
        validators=[
            DataRequired(message="Username is required."),
            Length(min=3, max=64, message="Username must be between 3 and 64 characters.")
        ]
    )
    email = StringField(
        "Email Address", 
        validators=[
            DataRequired(message="Email address is required."),
            Email(message="Please enter a valid email address."),
            Length(max=120, message="Email must be under 120 characters.")
        ]
    )
    password = PasswordField(
        "Password", 
        validators=[
            DataRequired(message="Password is required."),
            Length(min=8, max=128, message="Password must be at least 8 characters long.")
        ]
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(message="Please confirm the password."),
            EqualTo("password", message="Passwords must match.")
        ]
    )
    role_id = SelectField(
        "Assigned Privilege Role", 
        coerce=int, 
        validators=[DataRequired(message="Please assign a role to this account.")]
    )
    employee_id = SelectField(
        "Link to Employee",
        coerce=int,
        default=0,
        validators=[]
    )
    submit = SubmitField("Register Account")


class ChangePasswordForm(FlaskForm):
    """WTForms schema for handling self-initiated password changes."""
    current_password = PasswordField(
        "Current Password",
        validators=[DataRequired(message="Current password is required.")]
    )
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(message="New password is required."),
            Length(min=8, max=128, message="New password must be at least 8 characters long.")
        ]
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(message="Please confirm the new password."),
            EqualTo("new_password", message="Passwords must match.")
        ]
    )
    submit = SubmitField("Change Password")


class ResetPasswordForm(FlaskForm):
    """WTForms schema for handling administrative password resets."""
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(message="New password is required."),
            Length(min=8, max=128, message="New password must be at least 8 characters long.")
        ]
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(message="Please confirm the new password."),
            EqualTo("new_password", message="Passwords must match.")
        ]
    )
    submit = SubmitField("Reset Password")

