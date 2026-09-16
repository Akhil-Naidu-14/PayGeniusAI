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
from models.leave_type import LeaveType
from models.leave_balance import LeaveBalance
from models.leave_encashment import LeaveEncashment, LeaveEncashmentStatus
from models.payroll import Payroll
from blueprints.auth.services import AuthService
from blueprints.leave_encashment.services import LeaveEncashmentService

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

        # Seed Paid and Unpaid Leave Types
        paid_lt = LeaveType(
            name="Annual Leave",
            description="Paid Annual",
            is_paid=True,
            annual_quota=30
        )
        unpaid_lt = LeaveType(
            name="Unpaid Leave",
            description="Unpaid Sick",
            is_paid=False,
            annual_quota=10
        )
        db.session.add_all([paid_lt, unpaid_lt])
        db.session.commit()

        # Seed Leave Balance records
        paid_bal = LeaveBalance(
            employee_id=employee.id,
            leave_type_id=paid_lt.id,
            year=2026,
            total_allocated=30,
            used=5,
            remaining=25
        )
        unpaid_bal = LeaveBalance(
            employee_id=employee.id,
            leave_type_id=unpaid_lt.id,
            year=2026,
            total_allocated=10,
            used=0,
            remaining=10
        )
        db.session.add_all([paid_bal, unpaid_bal])
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
        paid_lt = LeaveType.query.filter_by(is_paid=True).first()
        unpaid_lt = LeaveType.query.filter_by(is_paid=False).first()
        yield {
            "employee_id": emp.id,
            "admin_user_id": admin.id,
            "paid_leave_type_id": paid_lt.id,
            "unpaid_leave_type_id": unpaid_lt.id
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


class TestLeaveEncashmentService:

    def test_cannot_encash_unpaid_leave_type(self, app, ctx):
        with app.app_context():
            res = LeaveEncashmentService.apply_encashment(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["unpaid_leave_type_id"],
                year=2026,
                days_requested=5
            )
            assert res["success"] is False
            assert "Unpaid" in res["message"]

    def test_cannot_exceed_remaining_balance(self, app, ctx):
        with app.app_context():
            # Remaining paid balance is 25, requesting 35
            res = LeaveEncashmentService.apply_encashment(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026,
                days_requested=35
            )
            assert res["success"] is False
            assert "exceed remaining balance" in res["message"]

    def test_apply_and_duplicate_encashment_blocked(self, app, ctx):
        with app.app_context():
            # Standard apply of 5 days (amount = (48000/30) * 5 = 8000)
            res1 = LeaveEncashmentService.apply_encashment(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026,
                days_requested=5
            )
            assert res1["success"] is True
            assert res1["total_amount"] == Decimal("8000.00")

            # Duplicate call for same year must be blocked
            res2 = LeaveEncashmentService.apply_encashment(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026,
                days_requested=3
            )
            assert res2["success"] is False
            assert "already exists" in res2["message"]

    def test_approve_deducts_balance_and_records_payroll_adjustment(self, app, ctx):
        with app.app_context():
            # 1. Apply
            res_apply = LeaveEncashmentService.apply_encashment(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026,
                days_requested=5
            )
            encash_id = res_apply["encashment_id"]

            # 2. Approve
            res_approve = LeaveEncashmentService.approve_encashment(
                encashment_id=encash_id,
                approver_id=ctx["admin_user_id"]
            )
            assert res_approve["success"] is True

            # 3. Assert leave balance is deducted: total 30, used was 5 -> now used is 10, remaining is 20
            bal = LeaveBalance.query.filter_by(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026
            ).first()
            assert bal.used == 10
            assert bal.remaining == 20

            # 4. Assert payroll adjustment is created (incentive = 8000)
            today = date.today()
            payroll = Payroll.query.filter_by(
                employee_id=ctx["employee_id"],
                month=today.month,
                year=today.year
            ).first()
            assert payroll is not None
            assert payroll.incentive == Decimal("8000.00")

    def test_reject_does_not_deduct_balance(self, app, ctx):
        with app.app_context():
            # 1. Apply
            res_apply = LeaveEncashmentService.apply_encashment(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026,
                days_requested=5
            )
            encash_id = res_apply["encashment_id"]

            # 2. Reject
            res_reject = LeaveEncashmentService.reject_encashment(
                encashment_id=encash_id,
                approver_id=ctx["admin_user_id"]
            )
            assert res_reject["success"] is True

            # 3. Assert leave balance is unchanged: used remains 5, remaining 25
            bal = LeaveBalance.query.filter_by(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["paid_leave_type_id"],
                year=2026
            ).first()
            assert bal.used == 5
            assert bal.remaining == 25


class TestLeaveEncashmentRoutes:

    def test_routes_access_control(self, client, app, ctx):
        # 1. Anonymous gets redirected/blocked (302)
        csrf = get_csrf_token(client)
        resp1 = client.post("/encashment/apply", json={
            "leave_type_id": ctx["paid_leave_type_id"],
            "year": 2026,
            "days_requested": 5
        }, headers={"X-CSRFToken": csrf})
        assert resp1.status_code == 302

        # 2. Logged in Employee can apply successfully
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        csrf = get_csrf_token(client)
        resp2 = client.post("/encashment/apply", json={
            "leave_type_id": ctx["paid_leave_type_id"],
            "year": 2026,
            "days_requested": 5
        }, headers={"X-CSRFToken": csrf})
        assert resp2.status_code == 200
        encash_id = resp2.json["encashment_id"]

        # Employee CANNOT view all encashment records (403)
        resp3 = client.get("/encashment/all")
        assert resp3.status_code == 403

        # Employee CANNOT approve/reject requests (403)
        resp4 = client.post(f"/encashment/{encash_id}/approve", headers={"X-CSRFToken": csrf})
        assert resp4.status_code == 403

        # 3. Logged in Admin can view and approve
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        csrf = get_csrf_token(client)
        resp5 = client.get("/encashment/all")
        assert resp5.status_code == 200
        assert len(resp5.json["data"]) == 1

        resp6 = client.post(f"/encashment/{encash_id}/approve", headers={"X-CSRFToken": csrf})
        assert resp6.status_code == 200
        assert resp6.json["success"] is True

