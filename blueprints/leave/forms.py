from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, ValidationError


class ApplyLeaveForm(FlaskForm):
    """Form for employees to apply for leave."""

    leave_type_id = SelectField(
        "Leave Type",
        coerce=int,
        validators=[DataRequired(message="Please select a leave type.")]
    )
    start_date = DateField(
        "Start Date",
        validators=[DataRequired(message="Start date is required.")]
    )
    end_date = DateField(
        "End Date",
        validators=[DataRequired(message="End date is required.")]
    )
    reason = TextAreaField("Reason (optional)")
    submit = SubmitField("Apply for Leave")

    def validate_end_date(self, field):
        if self.start_date.data and field.data:
            if field.data < self.start_date.data:
                raise ValidationError("End date must be on or after start date.")


class RejectLeaveForm(FlaskForm):
    """Minimal CSRF-protected form for rejecting a leave request."""
    submit = SubmitField("Reject")


class CancelLeaveForm(FlaskForm):
    """Minimal CSRF-protected form for cancelling a leave request."""
    submit = SubmitField("Cancel Leave")
