import re
import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.department import Department
from models.employee import Employee, EmployeeStatus
from models.payroll import Payroll
from models.attendance import Attendance, AttendanceStatus
from models.leave_type import LeaveType
from models.leave_request import LeaveRequest, LeaveRequestStatus
from models.government_rule import GovernmentRule
from models.payroll_validation_log import PayrollValidationLog
from blueprints.auth.services import AuthService
from blueprints.analytics.services import AnalyticsService

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

        # Department + Employee
        dept = Department(name="Engineering", code="ENG")
        db.session.add(dept)
        db.session.commit()

        employee = Employee(
            employee_code="EMP001",
            first_name="Alice",
            last_name="Smith",
            email="emp1@paygenius.ai",
            joining_date=date(2026, 1, 1),
            employment_type="Full-Time",
            basic_salary=Decimal("576000.00"),
            department_id=dept.id,
            status=EmployeeStatus.ACTIVE,
        )
        db.session.add(employee)
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
        emp = Employee.query.first()
        admin = User.query.filter_by(username="admin").first()
        yield {
            "employee_id": emp.id,
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


class TestAnalyticsService:

    def test_payroll_trend(self, app, ctx):
        with app.app_context():
            today = date.today()
            curr_m, curr_y = today.month, today.year
            if curr_m == 1:
                prev_m, prev_y = 12, curr_y - 1
            else:
                prev_m, prev_y = curr_m - 1, curr_y

            p1 = Payroll(
                employee_id=ctx["employee_id"],
                month=prev_m,
                year=prev_y,
                basic_salary=Decimal("10000.00"),
                gross_salary=Decimal("10000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("10000.00")
            )
            p2 = Payroll(
                employee_id=ctx["employee_id"],
                month=curr_m,
                year=curr_y,
                basic_salary=Decimal("12000.00"),
                gross_salary=Decimal("12000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("12000.00")
            )
            db.session.add_all([p1, p2])
            db.session.commit()
            res = AnalyticsService.get_payroll_trend(last_n_months=2)
            expected_prev_label = f"{prev_y}-{prev_m:02d}"
            expected_curr_label = f"{curr_y}-{curr_m:02d}"
            assert expected_prev_label in res["labels"]
            assert expected_curr_label in res["labels"]
            assert res["total_cost"] == [10000.0, 12000.0]

    def test_department_salary_distribution(self, app, ctx):
        with app.app_context():
            res = AnalyticsService.get_department_salary_distribution()
            assert "Engineering" in res["departments"]
            assert res["total_salaries"] == [576000.0]

    def test_attendance_trend(self, app, ctx):
        with app.app_context():
            today = date.today()
            att_date = today.replace(day=1)
            att = Attendance(
                employee_id=ctx["employee_id"],
                date=att_date,
                working_hours=Decimal("8.00"),
                overtime_hours=Decimal("2.00"),
                status=AttendanceStatus.PRESENT
            )
            db.session.add(att)
            db.session.commit()
            res = AnalyticsService.get_attendance_trend(last_n_months=1)
            expected_label = f"{today.year}-{today.month:02d}"
            assert expected_label in res["labels"]
            assert res["working_hours"] == [8.0]
            assert res["overtime_hours"] == [2.0]

    def test_leave_statistics(self, app, ctx):
        with app.app_context():
            # Seed Leave Requests
            lt = LeaveType(name="Sick", annual_quota=10)
            db.session.add(lt)
            db.session.commit()

            req = LeaveRequest(
                employee_id=ctx["employee_id"],
                leave_type_id=lt.id,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                days_requested=2,
                status=LeaveRequestStatus.APPROVED
            )
            db.session.add(req)
            db.session.commit()

            res = AnalyticsService.get_leave_statistics(year=2026)
            assert res["total_requests"] == 1
            assert res["approved"] == 1
            assert res["rejected"] == 0

    def test_compliance_risk_summary(self, app, ctx):
        with app.app_context():
            # Seed payroll + validation logs
            payroll = Payroll(
                employee_id=ctx["employee_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("48000.00"),
                status="Generated"
            )
            db.session.add(payroll)
            db.session.commit()

            log1 = PayrollValidationLog(
                payroll_id=payroll.id,
                rule_type="MINIMUM_WAGE",
                validation_status="PASS",
                validated_at=datetime.now(timezone.utc)
            )
            log2 = PayrollValidationLog(
                payroll_id=payroll.id,
                rule_type="PF_PERCENTAGE",
                validation_status="WARNING",
                validated_at=datetime.now(timezone.utc)
            )
            db.session.add_all([log1, log2])
            db.session.commit()

            res = AnalyticsService.get_compliance_risk_summary(month=8, year=2026)
            assert res["pass"] == 1
            assert res["warning"] == 1
            assert res["fail"] == 0


class TestAnalyticsRoutes:

    def test_route_access_controls(self, client, app, ctx):
        # 1. Anonymous redirected (302)
        resp1 = client.get("/analytics/payroll-trend")
        assert resp1.status_code == 302

        # 2. Regular employee forbidden (403)
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        resp2 = client.get("/analytics/payroll-trend")
        assert resp2.status_code == 403

        # 3. Administrator succeeds (200)
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        resp3 = client.get("/analytics/payroll-trend?last_n_months=1")
        assert resp3.status_code == 200
        assert resp3.json["success"] is True

    @patch("blueprints.ai.services.AIService.generate_executive_summary")
    def test_dashboard_access_and_rendering(self, mock_summary, client, app, ctx):
        mock_summary.return_value = {
            "summary": "Mock AI Executive Summary Text",
            "recommendation": "Mock Recommendation Text"
        }

        # 1. Anonymous redirected to login (302)
        resp1 = client.get("/dashboard")
        assert resp1.status_code == 302

        # 2. Standard Employee succeeds (200), does not call executive summary
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        resp2 = client.get("/dashboard")
        assert resp2.status_code == 200
        html = resp2.data.decode("utf-8")
        assert "Analytics Dashboard" in html
        assert "Gemini AI Executive Summary" not in html
        mock_summary.assert_not_called()

        # 3. Administrator succeeds (200), calls executive summary
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        mock_summary.reset_mock()
        resp3 = client.get("/dashboard")
        assert resp3.status_code == 200
        html_admin = resp3.data.decode("utf-8")
        assert "Analytics Dashboard" in html_admin
        assert "Gemini AI Executive Summary" in html_admin
        assert "Mock AI Executive Summary Text" in html_admin
        mock_summary.assert_called_once()

    def test_personal_analytics_routes(self, client, app, ctx):
        with app.app_context():
            emp_user = User.query.filter_by(username="emp1").first()
            emp_user.employee_id = ctx["employee_id"]
            # Intentionally set user email different from employee email
            emp_user.email = "different_email@paygenius.ai"
            db.session.commit()

        login_as(client, "different_email@paygenius.ai", "Emp@123451")

        resp1 = client.get("/analytics/personal/payroll-trend?last_n_months=6")
        assert resp1.status_code == 200
        assert resp1.json["success"] is True

        resp2 = client.get("/analytics/personal/attendance-trend?last_n_months=6")
        assert resp2.status_code == 200
        assert resp2.json["success"] is True

        resp3 = client.get("/analytics/personal/leave-stats/2026")
        assert resp3.status_code == 200
        assert resp3.json["success"] is True


