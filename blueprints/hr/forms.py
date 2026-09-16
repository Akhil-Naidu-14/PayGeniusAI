from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DateField, DecimalField
from wtforms.validators import DataRequired, Email, Length, Optional

class DepartmentForm(FlaskForm):
    """Form for creating or updating organizational departments."""
    name = StringField(
        "Department Name",
        validators=[DataRequired(), Length(max=100, message="Name must not exceed 100 characters.")]
    )
    code = StringField(
        "Department Code",
        validators=[DataRequired(), Length(max=20, message="Code must not exceed 20 characters.")]
    )
    description = StringField(
        "Description",
        validators=[Optional(), Length(max=255, message="Description must not exceed 255 characters.")]
    )


class EmployeeForm(FlaskForm):
    """Form for creating or updating employee directory records."""
    employee_code = StringField(
        "Employee Code",
        validators=[DataRequired(), Length(max=20, message="Employee Code must not exceed 20 characters.")]
    )
    first_name = StringField(
        "First Name",
        validators=[DataRequired(), Length(max=100, message="First Name must not exceed 100 characters.")]
    )
    last_name = StringField(
        "Last Name",
        validators=[DataRequired(), Length(max=100, message="Last Name must not exceed 100 characters.")]
    )
    email = StringField(
        "Email Address",
        validators=[DataRequired(), Email(message="Please enter a valid email address."), Length(max=120)]
    )
    phone = StringField(
        "Phone Number",
        validators=[Optional(), Length(max=20)]
    )
    gender = SelectField(
        "Gender",
        choices=[("", "Select Gender"), ("Male", "Male"), ("Female", "Female"), ("Other", "Other")],
        validators=[Optional()]
    )
    date_of_birth = DateField(
        "Date of Birth",
        format="%Y-%m-%d",
        validators=[Optional()]
    )
    address = TextAreaField(
        "Current Address",
        validators=[Optional()]
    )
    joining_date = DateField(
        "Joining Date",
        format="%Y-%m-%d",
        validators=[DataRequired(message="Joining date is required.")]
    )
    employment_type = SelectField(
        "Employment Type",
        choices=[("Full-Time", "Full-Time"), ("Part-Time", "Part-Time"), ("Contract", "Contract"), ("Intern", "Intern")],
        validators=[DataRequired(message="Employment type is required.")]
    )
    basic_salary = DecimalField(
        "Annual Basic Salary",
        places=2,
        validators=[DataRequired(message="Basic salary is required.")]
    )
    bank_account_number = StringField(
        "Bank Account Number",
        validators=[Optional(), Length(max=50)]
    )
    ifsc_code = StringField(
        "IFSC Code",
        validators=[Optional(), Length(max=20)]
    )
    pan_number = StringField(
        "PAN Number",
        validators=[Optional(), Length(max=20)]
    )
    aadhaar_number = StringField(
        "Aadhaar Number",
        validators=[Optional(), Length(max=20)]
    )
    emergency_contact = StringField(
        "Emergency Contact Number",
        validators=[Optional(), Length(max=20)]
    )
    status = SelectField(
        "Employment Status",
        choices=[("Active", "Active"), ("Inactive", "Inactive"), ("Resigned", "Resigned")],
        default="Active",
        validators=[DataRequired()]
    )
    department_id = SelectField(
        "Department",
        coerce=int,
        validators=[DataRequired(message="Please select a department.")]
    )
