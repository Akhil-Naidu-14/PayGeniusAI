import re
import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.department import Department
from models.employee import Employee, EmployeeStatus
from models.attendance import Attendance, AttendanceStatus
from models.leave_type import LeaveType
from models.leave_request import LeaveRequest, LeaveRequestStatus
from models.payroll import Payroll
from models.payroll_history import PayrollHistory
from models.government_rule import GovernmentRule
from models.payroll_validation_log import PayrollValidationLog
from blueprints.auth.services import AuthService
from blueprints.payroll.services import PayrollService

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
        emp_user1 = AuthService.create_user_by_admin(
            username="emp1", email="emp1@paygenius.ai",
            password="Emp@123451", role_id=emp_role.id
        )
        emp_user2 = AuthService.create_user_by_admin(
            username="emp2", email="emp2@paygenius.ai",
            password="Emp@123452", role_id=emp_role.id
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
            basic_salary=Decimal("576000.00"),
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
            basic_salary=Decimal("480000.00"),
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
    """
    Retrieves the CSRF token from the index page if logged in,
    otherwise from the login page.
    """
    response = client.get("/")
    html = response.data.decode("utf-8")
    match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    if not match:
        match = re.search(r'value="([^"]+)"[^>]+name="csrf_token"', html)
    if not match:
        response = client.get("/login")
        html = response.data.decode("utf-8")
        match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
        if not match:
            match = re.search(r'value="([^"]+)"[^>]+name="csrf_token"', html)
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


class TestPayrollCalculation:

    def test_overtime_pay_calculation(self):
        overtime_hours = Decimal("20.00")
        basic_salary = Decimal("48000.00")
        pay = PayrollService.calculate_overtime_pay(overtime_hours, basic_salary)
        assert pay == Decimal("6000.00")

    def test_unpaid_leave_deduction_calculation(self):
        basic_salary = Decimal("48000.00")
        unpaid_days = 5
        deduction = PayrollService.calculate_unpaid_leave_deduction(basic_salary, unpaid_days)
        assert deduction == Decimal("8000.00")

    def test_payroll_generation_happy_path(self, app, ctx):
        with app.app_context():
            for day in range(1, 6):
                att = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 8, day),
                    working_hours=Decimal("12.00"),
                    overtime_hours=Decimal("4.00"),
                    status=AttendanceStatus.PRESENT
                )
                db.session.add(att)
            db.session.commit()

            unpaid_lt = LeaveType(
                name="Unpaid Leave",
                description="Unpaid",
                is_paid=False,
                annual_quota=0
            )
            db.session.add(unpaid_lt)
            db.session.commit()

            leave_req = LeaveRequest(
                employee_id=ctx["emp1_id"],
                leave_type_id=unpaid_lt.id,
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 12),
                days_requested=3,
                status=LeaveRequestStatus.APPROVED
            )
            db.session.add(leave_req)
            db.session.commit()

            res = PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"],
                hra=Decimal("5000.00"),
                medical_allowance=Decimal("2000.00"),
                travel_allowance=Decimal("1500.00"),
                provident_fund=Decimal("4000.00"),
                income_tax=Decimal("3000.00")
            )

            assert res["success"] is True
            assert res["overtime_hours"] == Decimal("20.00")
            assert res["unpaid_days"] == 3
            assert res["gross_salary"] == Decimal("54000.00")
            assert res["net_salary"] == Decimal("38700.00")

    def test_payroll_generation_with_rule_defaults(self, app, ctx):
        with app.app_context():
            # Update emp1 joining_date to 2 years before Aug 2026
            emp1 = db.session.get(Employee, ctx["emp1_id"])
            emp1.joining_date = date(2024, 1, 1)

            rule_pf = GovernmentRule(
                rule_type="PF_PERCENTAGE",
                value=Decimal("12.00"),
                effective_from=date(2026, 1, 1),
                is_active=True
            )
            rule_pt = GovernmentRule(
                rule_type="PROFESSIONAL_TAX",
                value=Decimal("200.00"),
                effective_from=date(2026, 1, 1),
                is_active=True
            )
            rule_tax = GovernmentRule(
                rule_type="INCOME_TAX",
                value=Decimal("5.00"),
                effective_from=date(2026, 1, 1),
                is_active=True
            )
            rule_bonus = GovernmentRule(
                rule_type="BONUS_PERCENTAGE",
                value=Decimal("8.33"),
                effective_from=date(2026, 1, 1),
                is_active=True
            )
            rule_incentive = GovernmentRule(
                rule_type="INCENTIVE_PERCENTAGE",
                value=Decimal("5.00"),
                effective_from=date(2026, 1, 1),
                is_active=True
            )
            db.session.add_all([rule_pf, rule_pt, rule_tax, rule_bonus, rule_incentive])
            db.session.commit()

            res = PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"],
                apply_rule_defaults=True
            )

            assert res["success"] is True

            payroll = Payroll.query.filter_by(
                employee_id=ctx["emp1_id"], month=8, year=2026
            ).first()

            assert payroll is not None
            assert payroll.hra == Decimal("0.00")
            assert payroll.special_allowance == Decimal("0.00")
            assert payroll.medical_allowance > Decimal("0.00")
            assert payroll.travel_allowance > Decimal("0.00")
            assert payroll.bonus > Decimal("0.00")
            assert payroll.incentive > Decimal("0.00")
            assert payroll.provident_fund > Decimal("0.00")
            assert payroll.professional_tax > Decimal("0.00")
            assert payroll.income_tax > Decimal("0.00")
            assert payroll.total_deductions > Decimal("0.00")
            assert payroll.net_salary == payroll.gross_salary - payroll.total_deductions


    def test_payroll_prevent_duplicates(self, app, ctx):
        with app.app_context():
            res1 = PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )
            assert res1["success"] is True

            res2 = PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )
            assert res2["success"] is False


class TestPayrollRoutes:

    def test_payroll_routes_access_control(self, client, app, ctx):
        # 1. Anonymous user gets redirected/blocked (401/302)
        resp1 = client.get("/payroll/my")
        assert resp1.status_code == 302

        # 2. Login as regular employee emp1
        login_as(client, "emp1@paygenius.ai", "Emp@123451")

        # Regular employee cannot generate payroll (returns 403 via roles_required)
        csrf = get_csrf_token(client)
        resp2 = client.post(
            f"/payroll/generate/{ctx['emp1_id']}/8/2026",
            json={},
            headers={"X-CSRFToken": csrf}
        )
        assert resp2.status_code == 403

        # Regular employee can view own payroll (seed one first)
        with app.app_context():
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )

        resp3 = client.get(f"/payroll/{ctx['emp1_id']}/8/2026")
        assert resp3.status_code == 200
        assert resp3.json["success"] is True

        # Regular employee CANNOT view another employee's payroll
        resp4 = client.get(f"/payroll/{ctx['emp2_id']}/8/2026")
        assert resp4.status_code == 403

        # Regular employee can list own payroll history
        resp5 = client.get("/payroll/my")
        assert resp5.status_code == 200
        assert len(resp5.json["data"]) == 1

        # Regular employee cannot list month payroll
        resp6 = client.get("/payroll/list/8/2026")
        assert resp6.status_code == 403

    def test_admin_generation_and_listing(self, client, app, ctx):
        # Login as Admin
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        csrf = get_csrf_token(client)

        # Generate payroll for emp2
        resp1 = client.post(
            f"/payroll/generate/{ctx['emp2_id']}/9/2026",
            json={
                "hra": 4000,
                "bonus": 1000
            },
            headers={"X-CSRFToken": csrf}
        )
        assert resp1.status_code == 200
        assert resp1.json["success"] is True

        # Admin views emp2's payroll
        resp2 = client.get(f"/payroll/{ctx['emp2_id']}/9/2026")
        assert resp2.status_code == 200
        assert resp2.json["data"]["hra"] == "0.00"
        assert resp2.json["data"]["bonus"] == "1000.00"

        # Admin lists all payrolls for month
        resp3 = client.get("/payroll/list/9/2026")
        assert resp3.status_code == 200
        assert resp3.json["count"] == 1

    def test_payslip_download_security(self, client, app, ctx):
        # Seed a payroll record for emp1
        with app.app_context():
            res = PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )
            payroll_id = Payroll.query.filter_by(
                employee_id=ctx["emp1_id"], month=8, year=2026
            ).first().id

        # 1. Login as emp2 (unauthorized) and try to download emp1's payslip
        login_as(client, "emp2@paygenius.ai", "Emp@123452")
        resp1 = client.get(f"/payroll/{payroll_id}/download")
        assert resp1.status_code == 403

        # 2. Login as emp1 (authorized owner) and try to download
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        resp2 = client.get(f"/payroll/{payroll_id}/download")
        assert resp2.status_code == 200
        assert resp2.headers["Content-Type"] == "application/pdf"
        assert len(resp2.data) > 0

        # 3. Login as admin (authorized HR/Admin) and try to download
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        resp3 = client.get(f"/payroll/{payroll_id}/download")
        assert resp3.status_code == 200
        assert resp3.headers["Content-Type"] == "application/pdf"

    def test_payroll_ui_access_and_generate_download(self, client, app, ctx):
        # 1. Anonymous GET /payroll/ui redirects to login
        resp1 = client.get("/payroll/ui")
        assert resp1.status_code == 302

        # 2. Regular employee GET /payroll/ui gets 403 Forbidden
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        resp2 = client.get("/payroll/ui")
        assert resp2.status_code == 403

        # 3. Admin GET /payroll/ui returns 200 OK with template content
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        resp3 = client.get("/payroll/ui?month=8&year=2026")
        assert resp3.status_code == 200
        assert b"Payroll" in resp3.data
        assert b"EMP001" in resp3.data

        # 4. Admin POST /payroll/ui/generate-download/<emp1_id>/8/2026 returns 200 OK with downloading template
        csrf = get_csrf_token(client)
        resp4 = client.post(
            f"/payroll/ui/generate-download/{ctx['emp1_id']}/8/2026",
            data={"csrf_token": csrf},
            follow_redirects=False
        )
        assert resp4.status_code == 200
        assert b"Downloading Payslip" in resp4.data
        assert b"/download" in resp4.data

    def test_archive_payroll_month(self, client, app, ctx):
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        with app.app_context():
            res = PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )
            assert res["success"] is True

            p_before = Payroll.query.filter_by(
                employee_id=ctx["emp1_id"], month=8, year=2026, is_active=True
            ).first()
            assert p_before is not None

        csrf = get_csrf_token(client)
        resp = client.post(
            "/payroll/ui/archive/8/2026",
            data={"csrf_token": csrf},
            follow_redirects=False
        )

        assert resp.status_code == 302
        assert "/payroll/ui" in resp.headers["Location"]

        with app.app_context():
            p_after = db.session.get(Payroll, p_before.id)
            assert p_after is not None
            assert p_after.is_active is False


class TestPayrollAnomaly:

    def test_anomaly_no_historical_data(self, app, ctx):
        with app.app_context():
            # Seed current payroll
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )

            res = PayrollService.detect_payroll_anomaly(ctx["emp1_id"], 8, 2026)
            assert res["anomaly"] is False
            assert res["severity"] is None
            assert len(res["reasons"]) == 0

    def test_anomaly_salary_spike(self, app, ctx):
        with app.app_context():
            # Seed historical payroll (month 7, net salary 10,000)
            p_hist = Payroll(
                employee_id=ctx["emp1_id"],
                month=7,
                year=2026,
                basic_salary=Decimal("10000.00"),
                gross_salary=Decimal("10000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("10000.00")
            )
            db.session.add(p_hist)
            db.session.commit()

            # Seed current payroll (month 8, net salary > 10,000 * 1.5)
            # Bonus to increase salary
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"],
                bonus=Decimal("10000.00")  # will bump net salary to basic 48000 + bonus 10000 = 58000 > 10000 * 1.5
            )

            # We need standard working hours so low attendance is not triggered
            # Seed 20 days of standard working hours (160 hours total)
            for day in range(1, 21):
                att = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 8, day),
                    working_hours=Decimal("8.00"),
                    overtime_hours=Decimal("0.00"),
                    status=AttendanceStatus.PRESENT
                )
                db.session.add(att)
            db.session.commit()

            res = PayrollService.detect_payroll_anomaly(ctx["emp1_id"], 8, 2026)
            assert res["anomaly"] is True
            assert "Salary spike detected" in res["reasons"]
            assert res["severity"] == "Low"  # Only 1 rule triggered

    def test_anomaly_overtime_spike(self, app, ctx):
        with app.app_context():
            # Seed standard 160 working hours for both months to avoid low attendance
            for day in range(1, 21):
                # Month 7 (historical)
                att_h = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 7, day),
                    working_hours=Decimal("8.00"),
                    overtime_hours=Decimal("1.00"),  # 20 hours historical overtime total
                    status=AttendanceStatus.PRESENT
                )
                # Month 8 (current)
                att_c = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 8, day),
                    working_hours=Decimal("8.00"),
                    overtime_hours=Decimal("3.00"),  # 60 hours current overtime total > 20 * 2
                    status=AttendanceStatus.PRESENT
                )
                db.session.add_all([att_h, att_c])
            db.session.commit()

            # Seed historical payroll
            p_hist = Payroll(
                employee_id=ctx["emp1_id"],
                month=7,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("54000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("54000.00")
            )
            db.session.add(p_hist)
            db.session.commit()

            # Seed current payroll
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )

            res = PayrollService.detect_payroll_anomaly(ctx["emp1_id"], 8, 2026)
            assert res["anomaly"] is True
            assert "Overtime spike detected" in res["reasons"]

    def test_anomaly_excess_unpaid_leave(self, app, ctx):
        with app.app_context():
            # Seed 20 days of standard working hours for both months to avoid low attendance
            for day in range(1, 21):
                att_h = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 7, day),
                    working_hours=Decimal("8.00"),
                    status=AttendanceStatus.PRESENT
                )
                att_c = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 8, day),
                    working_hours=Decimal("8.00"),
                    status=AttendanceStatus.PRESENT
                )
                db.session.add_all([att_h, att_c])
            db.session.commit()

            # Seed historical payroll
            p_hist = Payroll(
                employee_id=ctx["emp1_id"],
                month=7,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("48000.00")
            )
            db.session.add(p_hist)
            db.session.commit()

            # Seed Unpaid Leave Type
            unpaid_lt = LeaveType(
                name="Unpaid Leave",
                description="Unpaid",
                is_paid=False,
                annual_quota=0
            )
            db.session.add(unpaid_lt)
            db.session.commit()

            # Seed 12 days approved unpaid leave in month 8 (> 10)
            leave_req = LeaveRequest(
                employee_id=ctx["emp1_id"],
                leave_type_id=unpaid_lt.id,
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 21),  # 12 days
                days_requested=12,
                status=LeaveRequestStatus.APPROVED
            )
            db.session.add(leave_req)
            db.session.commit()

            # Generate current payroll
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )

            res = PayrollService.detect_payroll_anomaly(ctx["emp1_id"], 8, 2026)
            assert res["anomaly"] is True
            assert "Excessive unpaid leave" in res["reasons"]

    def test_anomaly_low_attendance(self, app, ctx):
        with app.app_context():
            # Seed 20 days of standard working hours for Month 7 (historical)
            for day in range(1, 21):
                att_h = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 7, day),
                    working_hours=Decimal("8.00"),
                    status=AttendanceStatus.PRESENT
                )
                db.session.add(att_h)
            db.session.commit()

            # Seed historical payroll
            p_hist = Payroll(
                employee_id=ctx["emp1_id"],
                month=7,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("48000.00")
            )
            db.session.add(p_hist)
            db.session.commit()

            # Seed ONLY 5 days of working hours (40 hours total < 80 expected) for Month 8
            for day in range(1, 6):
                att_c = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 8, day),
                    working_hours=Decimal("8.00"),
                    status=AttendanceStatus.PRESENT
                )
                db.session.add(att_c)
            db.session.commit()

            # Generate current payroll
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"]
            )

            res = PayrollService.detect_payroll_anomaly(ctx["emp1_id"], 8, 2026)
            assert res["anomaly"] is True
            assert "Low attendance month" in res["reasons"]

    def test_anomaly_severity_calculation(self, app, ctx):
        with app.app_context():
            # Seed historical payroll (month 7, net salary 10,000)
            p_hist = Payroll(
                employee_id=ctx["emp1_id"],
                month=7,
                year=2026,
                basic_salary=Decimal("10000.00"),
                gross_salary=Decimal("10000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("10000.00")
            )
            db.session.add(p_hist)
            db.session.commit()

            # Seed current payroll (net salary > 10,000 * 1.5) -> Trigger 1: Salary spike
            PayrollService.generate_monthly_payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                generated_by=ctx["admin_user_id"],
                bonus=Decimal("10000.00")
            )

            # Seed ONLY 5 days of working hours (40 hours < 80 expected) -> Trigger 2: Low attendance month
            for day in range(1, 6):
                att = Attendance(
                    employee_id=ctx["emp1_id"],
                    date=date(2026, 8, day),
                    working_hours=Decimal("8.00"),
                    status=AttendanceStatus.PRESENT
                )
                db.session.add(att)
            db.session.commit()

            # Expect 2 triggers: "Salary spike detected", "Low attendance month"
            res = PayrollService.detect_payroll_anomaly(ctx["emp1_id"], 8, 2026)
            assert res["anomaly"] is True
            assert len(res["reasons"]) == 2
            assert res["severity"] == "Medium"


class TestGovernmentRuleValidation:

    def test_validation_clean_payroll(self, app, ctx):
        with app.app_context():
            # Seed a government rule for minimum wage and PF
            rule1 = GovernmentRule(
                rule_type="MINIMUM_WAGE",
                value=Decimal("15000.00"),
                effective_from=date(2026, 8, 1),
                is_active=True
            )
            rule2 = GovernmentRule(
                rule_type="PF_PERCENTAGE",
                value=Decimal("12.00"),
                effective_from=date(2026, 8, 1),
                is_active=True
            )
            db.session.add_all([rule1, rule2])
            db.session.commit()

            # Seed clean payroll
            # basic salary 48,000 >= 15,000 threshold
            # provident fund is exactly 48,000 * 0.12 = 5,760
            payroll = Payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("48000.00"),
                hra=Decimal("0.00"),
                gross_salary=Decimal("48000.00"),
                provident_fund=Decimal("5760.00"),
                total_deductions=Decimal("5760.00"),
                net_salary=Decimal("42240.00"),
                status="Generated"
            )
            db.session.add(payroll)
            db.session.commit()

            res = PayrollService.validate_payroll_against_government_rules(payroll.id)
            assert res["overall_status"] == "PASS"
            assert len(res["violations"]) == 0
            assert res["logs_created"] == 2

            # Assert validation logs exist in DB
            logs = PayrollValidationLog.query.filter_by(payroll_id=payroll.id).all()
            assert len(logs) == 2
            assert all(log.validation_status == "PASS" for log in logs)

    def test_validation_pf_mismatch_warning(self, app, ctx):
        with app.app_context():
            # Seed 12% PF rule
            rule = GovernmentRule(
                rule_type="PF_PERCENTAGE",
                value=Decimal("12.00"),
                effective_from=date(2026, 8, 1),
                is_active=True
            )
            db.session.add(rule)
            db.session.commit()

            # Seed payroll with incorrect PF (e.g. 5,000 instead of 5,760)
            payroll = Payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                provident_fund=Decimal("5000.00"),  # Mismatch!
                total_deductions=Decimal("5000.00"),
                net_salary=Decimal("43000.00"),
                status="Generated"
            )
            db.session.add(payroll)
            db.session.commit()

            res = PayrollService.validate_payroll_against_government_rules(payroll.id)
            assert res["overall_status"] == "WARNING"
            assert len(res["violations"]) == 1
            assert "PF mismatch" in res["violations"][0]

            log = PayrollValidationLog.query.filter_by(payroll_id=payroll.id).first()
            assert log.validation_status == "WARNING"

    def test_validation_below_minimum_wage_fail(self, app, ctx):
        with app.app_context():
            # Seed minimum wage rule of 15,000
            rule = GovernmentRule(
                rule_type="MINIMUM_WAGE",
                value=Decimal("15000.00"),
                effective_from=date(2026, 8, 1),
                is_active=True
            )
            db.session.add(rule)
            db.session.commit()

            # Seed payroll below minimum wage
            payroll = Payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("12000.00"),  # Below threshold!
                gross_salary=Decimal("12000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("12000.00"),
                status="Generated"
            )
            db.session.add(payroll)
            db.session.commit()

            res = PayrollService.validate_payroll_against_government_rules(payroll.id)
            assert res["overall_status"] == "FAIL"
            assert len(res["violations"]) == 1
            assert "minimum wage" in res["violations"][0]

            log = PayrollValidationLog.query.filter_by(payroll_id=payroll.id).first()
            assert log.validation_status == "FAIL"

    def test_validation_deduction_cap_exceeded_fail(self, app, ctx):
        with app.app_context():
            # Seed 50% max deduction cap rule
            rule = GovernmentRule(
                rule_type="MAX_DEDUCTION_CAP",
                value=Decimal("50.00"),
                effective_from=date(2026, 8, 1),
                is_active=True
            )
            db.session.add(rule)
            db.session.commit()

            # Seed payroll with deductions exceeding 50% of gross salary
            # Gross = 10,000, deductions = 6,000 (60% > 50%)
            payroll = Payroll(
                employee_id=ctx["emp1_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("10000.00"),
                gross_salary=Decimal("10000.00"),
                total_deductions=Decimal("6000.00"),  # > 50%
                net_salary=Decimal("4000.00"),
                status="Generated"
            )
            db.session.add(payroll)
            db.session.commit()

            res = PayrollService.validate_payroll_against_government_rules(payroll.id)
            assert res["overall_status"] == "FAIL"
            assert len(res["violations"]) == 1
            assert "exceeds cap" in res["violations"][0]

            log = PayrollValidationLog.query.filter_by(payroll_id=payroll.id).first()
            assert log.validation_status == "FAIL"


