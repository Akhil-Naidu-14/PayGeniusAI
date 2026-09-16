import re
from io import BytesIO
import pytest
import pandas as pd
from datetime import date, datetime, timezone
from decimal import Decimal

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.department import Department
from models.employee import Employee, EmployeeStatus
from models.attendance import Attendance, AttendanceStatus
from blueprints.auth.services import AuthService
from blueprints.attendance_upload.services import AttendanceUploadService

@pytest.fixture
def app():
    """Create isolated in-memory test app with required seeding."""
    application = create_app("testing")
    with application.app_context():
        db.create_all()

        # Roles
        admin_role = Role(name=RoleType.ADMIN, description="Admin")
        hr_role = Role(name=RoleType.HR, description="HR")
        emp_role = Role(name=RoleType.EMPLOYEE, description="Employee")
        db.session.add_all([admin_role, hr_role, emp_role])
        db.session.commit()

        # Users
        admin_user = AuthService.create_user_by_admin(
            username="admin", email="admin@paygenius.ai",
            password="Admin@12345", role_id=admin_role.id
        )
        emp_user = AuthService.create_user_by_admin(
            username="emp1", email="emp1@paygenius.ai",
            password="Emp@123451", role_id=emp_role.id
        )

        # Department + Employee 1
        dept = Department(name="Engineering", code="ENG")
        db.session.add(dept)
        db.session.commit()

        employee1 = Employee(
            employee_code="EMP001",
            first_name="Alice",
            last_name="Smith",
            email="emp1@paygenius.ai",
            joining_date=date(2026, 1, 1),
            employment_type="Full-Time",
            basic_salary=576000,
            department_id=dept.id,
            status=EmployeeStatus.ACTIVE,
        )
        db.session.add(employee1)

        # Employee 2
        employee2 = Employee(
            employee_code="EMP002",
            first_name="Bob",
            last_name="Jones",
            email="emp2@paygenius.ai",
            joining_date=date(2026, 1, 1),
            employment_type="Full-Time",
            basic_salary=480000,
            department_id=dept.id,
            status=EmployeeStatus.ACTIVE,
        )
        db.session.add(employee2)
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def ctx(app):
    with app.app_context():
        emp1 = Employee.query.filter_by(employee_code="EMP001").first()
        emp2 = Employee.query.filter_by(employee_code="EMP002").first()
        admin = User.query.filter_by(username="admin").first()
        yield {
            "emp1_id": emp1.id,
            "emp2_id": emp2.id,
            "admin_user_id": admin.id
        }

def get_csrf_token(client):
    response = client.get("/")
    html = response.data.decode("utf-8")
    match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    if not match:
        match = re.search(r'value="([^"]+)"[^>]+name="csrf_token"', html)
    if not match:
        response = client.get("/login")
        html = response.data.decode("utf-8")
        match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    return match.group(1) if match else None

def logout(client):
    csrf_token = get_csrf_token(client)
    return client.post("/logout", data={
        "csrf_token": csrf_token
    }, follow_redirects=True)

def login_as(client, username_or_email, password):
    logout(client)
    csrf_token = get_csrf_token(client)
    return client.post("/login", data={
        "csrf_token": csrf_token,
        "username_or_email": username_or_email,
        "password": password
    }, follow_redirects=True)

def generate_test_excel(rows):
    df = pd.DataFrame(rows)
    out = BytesIO()
    df.to_excel(out, index=False, engine='openpyxl')
    out.seek(0)
    return out


class TestAttendanceUploadService:

    def test_upload_valid_excel(self, app, ctx):
        # Generate valid Excel data
        excel_rows = [
            {
                "employee_code": "EMP001",
                "date": "2026-08-01",
                "check_in": "2026-08-01 09:00:00",
                "check_out": "2026-08-01 17:00:00"
            },
            {
                "employee_code": "EMP002",
                "date": "2026-08-01",
                "check_in": "2026-08-01 08:45:00",
                "check_out": "2026-08-01 17:15:00"
            }
        ]
        excel_file = generate_test_excel(excel_rows)

        with app.app_context():
            res = AttendanceUploadService.upload_attendance_excel(excel_file)
            assert res["success"] is True
            assert res["records_processed"] == 2
            assert res["records_updated"] == 0
            assert res["records_failed"] == 0
            assert len(res["errors"]) == 0

            # Verify in DB
            att1 = Attendance.query.filter_by(employee_id=ctx["emp1_id"], date=date(2026, 8, 1)).first()
            assert att1 is not None
            assert att1.status == "Present"

    def test_late_minutes_and_early_leave_computation(self, app, ctx):
        excel_rows = [
            {
                "employee_code": "EMP001",
                "date": "2026-06-04",
                "check_in": "2026-06-04 09:03:00",
                "check_out": "2026-06-04 16:50:00"
            }
        ]
        excel_file = generate_test_excel(excel_rows)

        with app.app_context():
            res = AttendanceUploadService.upload_attendance_excel(excel_file)
            assert res["success"] is True
            assert res["records_processed"] == 1

            att = Attendance.query.filter_by(employee_id=ctx["emp1_id"], date=date(2026, 6, 4)).first()
            assert att is not None
            assert att.late_minutes == 3
            assert att.early_leave_minutes == 10


    def test_upload_excel_with_duplicates_and_errors(self, app, ctx):
        excel_rows = [
            # Valid row
            {
                "employee_code": "EMP001",
                "date": "2026-08-01",
                "check_in": "2026-08-01 09:00:00",
                "check_out": "2026-08-01 17:00:00"
            },
            # Duplicate row in same file (fails)
            {
                "employee_code": "EMP001",
                "date": "2026-08-01",
                "check_in": "2026-08-01 09:15:00",
                "check_out": "2026-08-01 17:00:00"
            },
            # Non-existent employee (fails)
            {
                "employee_code": "EMP999",
                "date": "2026-08-01",
                "check_in": "2026-08-01 09:00:00",
                "check_out": "2026-08-01 17:00:00"
            },
            # Invalid date format (fails)
            {
                "employee_code": "EMP002",
                "date": "invalid-date",
                "check_in": "2026-08-01 09:00:00",
                "check_out": "2026-08-01 17:00:00"
            }
        ]
        excel_file = generate_test_excel(excel_rows)

        with app.app_context():
            res = AttendanceUploadService.upload_attendance_excel(excel_file)
            assert res["success"] is True
            assert res["records_processed"] == 1
            assert res["records_failed"] == 3
            assert len(res["errors"]) == 3

    def test_upload_excel_updates_existing_records(self, app, ctx):
        # 1. Seed initial record
        with app.app_context():
            att = Attendance(
                employee_id=ctx["emp1_id"],
                date=date(2026, 8, 1),
                status=AttendanceStatus.PRESENT
            )
            db.session.add(att)
            db.session.commit()

        # 2. Upload Excel overriding this record
        excel_rows = [
            {
                "employee_code": "EMP001",
                "date": "2026-08-01",
                "check_in": "2026-08-01 09:00:00",
                "check_out": "2026-08-01 18:00:00"
            }
        ]
        excel_file = generate_test_excel(excel_rows)

        with app.app_context():
            res = AttendanceUploadService.upload_attendance_excel(excel_file)
            assert res["success"] is True
            assert res["records_processed"] == 1
            assert res["records_updated"] == 1
            assert res["records_failed"] == 0

            # Verify update
            updated = Attendance.query.filter_by(employee_id=ctx["emp1_id"], date=date(2026, 8, 1)).first()
            assert updated.working_hours == Decimal("9.00")


class TestAttendanceUploadRoutes:

    def test_upload_route_access_control(self, client, app, ctx):
        excel_rows = [
            {"employee_code": "EMP001", "date": "2026-08-01", "check_in": "2026-08-01 09:00:00", "check_out": "2026-08-01 17:00:00"}
        ]

        # 1. Anonymous gets redirected/blocked (with CSRF token passed to bypass CSRF 400 error)
        excel_file1 = generate_test_excel(excel_rows)
        csrf = get_csrf_token(client)
        resp1 = client.post(
            "/attendance/upload",
            data={
                "csrf_token": csrf,
                "excel_file": (excel_file1, "attendance.xlsx")
            },
            content_type="multipart/form-data"
        )
        assert resp1.status_code == 302

        # 2. Employee role gets 403
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        excel_file2 = generate_test_excel(excel_rows)
        csrf = get_csrf_token(client)
        resp2 = client.post(
            "/attendance/upload",
            data={
                "csrf_token": csrf,
                "excel_file": (excel_file2, "attendance.xlsx")
            },
            content_type="multipart/form-data"
        )
        assert resp2.status_code == 403

        # 3. Admin succeeds
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        excel_file3 = generate_test_excel(excel_rows)
        csrf = get_csrf_token(client)
        resp3 = client.post(
            "/attendance/upload",
            data={
                "csrf_token": csrf,
                "excel_file": (excel_file3, "attendance.xlsx")
            },
            content_type="multipart/form-data"
        )
        assert resp3.status_code == 200
        assert resp3.json["success"] is True
        assert resp3.json["records_processed"] == 1

    def test_upload_ui_route_access_control(self, client, app, ctx):
        # 1. Unauthenticated gets 302 redirect
        resp1 = client.get("/attendance/upload-ui")
        assert resp1.status_code == 302

        # 2. Employee role gets 403 Forbidden
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        resp2 = client.get("/attendance/upload-ui")
        assert resp2.status_code == 403

        # 3. Admin gets 200 OK
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        resp3 = client.get("/attendance/upload-ui")
        assert resp3.status_code == 200

    def test_upload_ui_get_renders_form(self, client, app, ctx):
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        resp = client.get("/attendance/upload-ui")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert 'name="excel_file"' in html

    def test_upload_ui_post_valid_excel_renders_success_metrics(self, client, app, ctx):
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        excel_rows = [
            {"employee_code": "EMP001", "date": "2026-08-01", "check_in": "2026-08-01 09:00:00", "check_out": "2026-08-01 17:00:00"},
            {"employee_code": "EMP002", "date": "2026-08-01", "check_in": "2026-08-01 08:45:00", "check_out": "2026-08-01 17:15:00"}
        ]
        excel_file = generate_test_excel(excel_rows)
        csrf = get_csrf_token(client)

        resp = client.post(
            "/attendance/upload-ui",
            data={
                "csrf_token": csrf,
                "excel_file": (excel_file, "attendance.xlsx")
            },
            content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Upload Results Summary" in html
        assert "Created" in html
        assert "Updated" in html
        assert "Failed" in html
        assert "Processed" in html

        # Verify DB insertion
        with app.app_context():
            att1 = Attendance.query.filter_by(employee_id=ctx["emp1_id"], date=date(2026, 8, 1)).first()
            assert att1 is not None

    def test_upload_ui_post_invalid_extension_shows_error(self, client, app, ctx):
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        csrf = get_csrf_token(client)
        resp = client.post(
            "/attendance/upload-ui",
            data={
                "csrf_token": csrf,
                "excel_file": (BytesIO(b"dummy text content"), "attendance.txt")
            },
            content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Only Excel (.xlsx) files are supported." in html

