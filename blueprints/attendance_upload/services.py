import logging
from datetime import date, datetime, timezone
import pandas as pd
from sqlalchemy import extract

from extensions import db
from models.employee import Employee
from models.attendance import Attendance
from blueprints.attendance.services import AttendanceService

logger = logging.getLogger(__name__)

class AttendanceUploadService:
    """
    AttendanceUploadService provides the core service logic for bulk uploading
    attendance records from Excel (.xlsx) files.
    """

    @staticmethod
    def upload_attendance_excel(file_stream) -> dict:
        """
        Parses an attendance Excel (.xlsx) stream using Pandas.
        Inserts or updates attendance records using AttendanceService.
        Wraps all successful operations inside a single database transaction block.

        Returns a structured summary:
        {
            "success": True,
            "records_processed": X,
            "records_updated": Y,
            "records_failed": Z,
            "errors": [...]
        }
        """
        try:
            # 1. Parse Excel file using Pandas
            df = pd.read_excel(file_stream, engine='openpyxl')
        except Exception as e:
            logger.error("Failed to parse Excel file: %s", str(e))
            return {
                "success": False,
                "message": f"Failed to parse Excel file: {str(e)}",
                "records_processed": 0,
                "records_updated": 0,
                "records_failed": 0
            }

        # Normalize column names to lowercase and strip whitespace
        df.columns = [str(col).strip().lower() for col in df.columns]

        # Verify expected columns exist
        expected_cols = ["employee_code", "date", "check_in", "check_out"]
        missing_cols = [col for col in expected_cols if col not in df.columns]
        if missing_cols:
            return {
                "success": False,
                "message": f"Missing expected columns in Excel file: {', '.join(missing_cols)}",
                "records_processed": 0,
                "records_updated": 0,
                "records_failed": 0
            }

        records_processed = 0
        records_updated = 0
        records_failed = 0
        errors = []

        # Track (employee_code, date) processed in THIS file to prevent duplicates within the upload
        seen_in_file = set()

        try:
            for idx, row in df.iterrows():
                row_num = idx + 2 # 1-based index + 1 for header row
                
                emp_code = row.get("employee_code")
                row_date = row.get("date")
                row_check_in = row.get("check_in")
                row_check_out = row.get("check_out")

                # Basic empty checks
                if pd.isna(emp_code) or pd.isna(row_date):
                    records_failed += 1
                    errors.append(f"Row {row_num}: Missing employee_code or date.")
                    continue

                emp_code_str = str(emp_code).strip()

                # Parse Date
                try:
                    parsed_date = pd.to_datetime(row_date).to_pydatetime().date()
                except Exception:
                    records_failed += 1
                    errors.append(f"Row {row_num}: Invalid date format.")
                    continue

                # Check for duplicate in current upload file
                dup_key = (emp_code_str, parsed_date)
                if dup_key in seen_in_file:
                    records_failed += 1
                    errors.append(f"Row {row_num}: Duplicate attendance for employee {emp_code_str} on date {parsed_date} inside file.")
                    continue
                seen_in_file.add(dup_key)

                # Lookup Employee
                emp = Employee.query.filter_by(employee_code=emp_code_str, is_active=True).first()
                if not emp:
                    records_failed += 1
                    errors.append(f"Row {row_num}: Active employee with code '{emp_code_str}' not found.")
                    continue

                # Parse check_in and check_out timestamps
                check_in_dt = None
                check_out_dt = None

                try:
                    if not pd.isna(row_check_in):
                        check_in_dt = pd.to_datetime(row_check_in).to_pydatetime()
                        if check_in_dt.tzinfo is None:
                            check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
                    
                    if not pd.isna(row_check_out):
                        check_out_dt = pd.to_datetime(row_check_out).to_pydatetime()
                        if check_out_dt.tzinfo is None:
                            check_out_dt = check_out_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    records_failed += 1
                    errors.append(f"Row {row_num}: Invalid check-in/out datetime format.")
                    continue

                # Determine if it's a new record or an update
                existing = Attendance.query.filter_by(
                    employee_id=emp.id,
                    date=parsed_date
                ).first()
                
                is_update = existing is not None

                # Use AttendanceService to insert/update record
                success, status_code, _ = AttendanceService.mark_attendance(
                    employee_id=emp.id,
                    target_date=parsed_date,
                    status="Present",
                    check_in=check_in_dt,
                    check_out=check_out_dt
                )

                if success:
                    records_processed += 1
                    if is_update:
                        records_updated += 1
                else:
                    records_failed += 1
                    errors.append(f"Row {row_num}: AttendanceService failed with code {status_code}.")
            
            # Commit all changes at the end
            db.session.commit()

        except Exception as tx_err:
            logger.error("Transaction failed during attendance upload: %s", str(tx_err))
            db.session.rollback()
            return {
                "success": False,
                "message": f"Database transaction error: {str(tx_err)}",
                "records_processed": 0,
                "records_updated": 0,
                "records_failed": len(df)
            }

        return {
            "success": True,
            "records_processed": records_processed,
            "records_updated": records_updated,
            "records_failed": records_failed,
            "errors": errors
        }
