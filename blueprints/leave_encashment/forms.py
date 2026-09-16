from flask_wtf import FlaskForm
from wtforms import IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange

class LeaveEncashmentForm(FlaskForm):
    """
    LeaveEncashmentForm validates WTForms payloads for requesting leave conversions.
    """
    leave_type_id = IntegerField("Leave Type ID", validators=[DataRequired()])
    year = IntegerField("Year", validators=[DataRequired()])
    days_requested = IntegerField("Days Requested", validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField("Apply")
