from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import SubmitField

class AttendanceUploadForm(FlaskForm):
    """
    Form for HR/Admin to upload bulk attendance records (.xlsx).
    """
    excel_file = FileField(
        "Attendance Excel File (.xlsx)",
        validators=[
            FileRequired(message="Please select a file to upload."),
            FileAllowed(["xlsx"], "Only Excel (.xlsx) files are supported.")
        ]
    )
    submit = SubmitField("Upload Records")
