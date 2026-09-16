"""
Tests for the Leave Management module (Phase 2).

Covers:
  - Overlap detection
  - Leave quota / insufficient balance
  - Approval deducts balance correctly
  - Reject does NOT deduct balance
  - Cancel only allowed when Pending
  - Demo data seeder is idempotent (no errors on double-run)
"""

import pytest
from datetime import date, timedelta

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.department import Department
from models.employee import Employee, EmployeeStatus
from models.leave_type import LeaveType
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest, LeaveRequestStatus
from blueprints.auth.services import AuthService
from blueprints.leave.services import LeaveService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Create an isolated in-memory test app with all required seed data."""
    application = create_app("testing")
    with application.app_context():
        db.create_all()

        # Roles
        admin_role = Role(name=RoleType.ADMIN, description="Admin")
        hr_role    = Role(name=RoleType.HR,    description="HR")
        emp_role   = Role(name=RoleType.EMPLOYEE, description="Employee")
        db.session.add_all([admin_role, hr_role, emp_role])
        db.session.commit()

        # Users
        admin_user = AuthService.create_user_by_admin(
            username="admin", email="admin@paygenius.ai",
            password="Admin@12345", role_id=admin_role.id
        )
        hr_user = AuthService.create_user_by_admin(
            username="hr", email="hr@paygenius.ai",
            password="Hr@12345", role_id=hr_role.id
        )
        emp_user = AuthService.create_user_by_admin(
            username="emp", email="emp@paygenius.ai",
            password="Emp@12345", role_id=emp_role.id
        )

        # Department + Employee
        dept = Department(name="Engineering", code="ENG")
        db.session.add(dept)
        db.session.commit()

        from decimal import Decimal
        employee = Employee(
            employee_code="EMP001",
            first_name="Alice",
            last_name="Smith",
            email="emp@paygenius.ai",  # matches emp_user for _resolve_employee_id
            joining_date=date(2023, 1, 1),
            employment_type="Full-Time",
            basic_salary=Decimal("600000"),
            department_id=dept.id,
            status=EmployeeStatus.ACTIVE,
        )
        db.session.add(employee)
        db.session.commit()

        # Leave type
        annual = LeaveType(
            name="Annual Leave",
            description="Paid annual leave.",
            is_paid=True,
            annual_quota=18,
        )
        db.session.add(annual)
        db.session.commit()

        # Leave balance: 10 days remaining
        year = date.today().year
        balance = LeaveBalance(
            employee_id=employee.id,
            leave_type_id=annual.id,
            year=year,
            total_allocated=10,
            used=0,
            remaining=10,
        )
        db.session.add(balance)
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def ctx(app):
    """Push application context and return useful IDs."""
    with app.app_context():
        emp = Employee.query.first()
        lt  = LeaveType.query.first()
        user = User.query.filter_by(username="hr").first()
        yield {"employee_id": emp.id, "leave_type_id": lt.id, "hr_user_id": user.id}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _today_plus(n):
    return date.today() + timedelta(days=n)


# ---------------------------------------------------------------------------
# Tests: apply_leave
# ---------------------------------------------------------------------------

class TestApplyLeave:

    def test_successful_application(self, app, ctx):
        with app.app_context():
            start = _today_plus(5)
            end   = _today_plus(7)
            ok, code, req = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"], start, end
            )
            assert ok is True
            assert code == "SUCCESS"
            assert req is not None
            assert req.days_requested == 3
            assert req.status == LeaveRequestStatus.PENDING

    def test_invalid_dates(self, app, ctx):
        with app.app_context():
            ok, code, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(7), _today_plus(3)   # end before start
            )
            assert ok is False
            assert code == "INVALID_DATES"

    def test_insufficient_balance(self, app, ctx):
        with app.app_context():
            # Request 11 days but only 10 remaining
            ok, code, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(1), _today_plus(11)  # 11 days
            )
            assert ok is False
            assert code == "INSUFFICIENT"

    def test_no_balance_record(self, app, ctx):
        with app.app_context():
            # Force a date in a year with no balance record
            ok, code, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                date(2020, 6, 1), date(2020, 6, 3)
            )
            assert ok is False
            assert code == "NO_BALANCE"

    def test_overlap_blocked(self, app, ctx):
        with app.app_context():
            start = _today_plus(5)
            end   = _today_plus(7)
            # First request succeeds
            ok1, _, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"], start, end
            )
            assert ok1 is True

            # Overlapping second request is blocked
            ok2, code, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(6), _today_plus(9)   # overlaps by 1 day
            )
            assert ok2 is False
            assert code == "OVERLAP"

    def test_non_overlapping_allowed(self, app, ctx):
        with app.app_context():
            ok1, _, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(1), _today_plus(2)
            )
            assert ok1 is True

            # Adjacent but non-overlapping
            ok2, code, _ = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(3), _today_plus(4)
            )
            assert ok2 is True
            assert code == "SUCCESS"


# ---------------------------------------------------------------------------
# Tests: approve_leave
# ---------------------------------------------------------------------------

class TestApproveLeave:

    def _create_pending(self, app, ctx, days=3):
        """Helper: creates a Pending request and returns its id."""
        with app.app_context():
            ok, _, req = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(10), _today_plus(10 + days - 1)
            )
            assert ok, "Prerequisite apply_leave failed"
            return req.id

    def test_approve_deducts_balance(self, app, ctx):
        req_id = self._create_pending(app, ctx, days=3)
        with app.app_context():
            bal_before = LeaveBalance.query.filter_by(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["leave_type_id"],
                year=date.today().year,
            ).first()
            remaining_before = bal_before.remaining

            ok, code, req = LeaveService.approve_leave(req_id, ctx["hr_user_id"])
            assert ok is True
            assert code == "SUCCESS"
            assert req.status == LeaveRequestStatus.APPROVED

            bal_after = LeaveBalance.query.filter_by(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["leave_type_id"],
                year=date.today().year,
            ).first()
            assert bal_after.used      == 3
            assert bal_after.remaining == remaining_before - 3
            # Invariant: remaining == total_allocated - used
            assert bal_after.remaining == bal_after.total_allocated - bal_after.used

    def test_approve_sets_approver_and_timestamp(self, app, ctx):
        req_id = self._create_pending(app, ctx, days=2)
        with app.app_context():
            LeaveService.approve_leave(req_id, ctx["hr_user_id"])
            req = db.session.get(LeaveRequest, req_id)
            assert req.approved_by == ctx["hr_user_id"]
            assert req.approved_at is not None

    def test_approve_already_approved_blocked(self, app, ctx):
        req_id = self._create_pending(app, ctx, days=2)
        with app.app_context():
            LeaveService.approve_leave(req_id, ctx["hr_user_id"])
            ok, code, _ = LeaveService.approve_leave(req_id, ctx["hr_user_id"])
            assert ok is False
            assert code == "ALREADY_ACTIONED"

    def test_approve_flips_attendance_to_on_leave(self, app, ctx):
        from models.attendance import Attendance, AttendanceStatus
        req_id = self._create_pending(app, ctx, days=2)
        with app.app_context():
            req = db.session.get(LeaveRequest, req_id)
            start, end = req.start_date, req.end_date
            LeaveService.approve_leave(req_id, ctx["hr_user_id"])
            records = Attendance.query.filter(
                Attendance.employee_id == ctx["employee_id"],
                Attendance.date >= start,
                Attendance.date <= end,
            ).all()
            assert len(records) == 2
            for r in records:
                assert r.status == AttendanceStatus.ON_LEAVE


# ---------------------------------------------------------------------------
# Tests: reject_leave
# ---------------------------------------------------------------------------

class TestRejectLeave:

    def _create_pending(self, app, ctx, days=2):
        with app.app_context():
            ok, _, req = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(20), _today_plus(20 + days - 1)
            )
            assert ok
            return req.id

    def test_reject_does_not_deduct_balance(self, app, ctx):
        req_id = self._create_pending(app, ctx, days=2)
        with app.app_context():
            bal_before = LeaveBalance.query.filter_by(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["leave_type_id"],
                year=date.today().year,
            ).first()
            remaining_before = bal_before.remaining

            ok, code, _ = LeaveService.reject_leave(req_id, ctx["hr_user_id"])
            assert ok is True
            assert code == "SUCCESS"

            bal_after = LeaveBalance.query.filter_by(
                employee_id=ctx["employee_id"],
                leave_type_id=ctx["leave_type_id"],
                year=date.today().year,
            ).first()
            assert bal_after.remaining == remaining_before   # unchanged

    def test_reject_sets_status(self, app, ctx):
        req_id = self._create_pending(app, ctx, days=2)
        with app.app_context():
            LeaveService.reject_leave(req_id, ctx["hr_user_id"])
            req = db.session.get(LeaveRequest, req_id)
            assert req.status == LeaveRequestStatus.REJECTED

    def test_reject_already_rejected_blocked(self, app, ctx):
        req_id = self._create_pending(app, ctx, days=2)
        with app.app_context():
            LeaveService.reject_leave(req_id, ctx["hr_user_id"])
            ok, code, _ = LeaveService.reject_leave(req_id, ctx["hr_user_id"])
            assert ok is False
            assert code == "ALREADY_ACTIONED"


# ---------------------------------------------------------------------------
# Tests: cancel_leave
# ---------------------------------------------------------------------------

class TestCancelLeave:

    def _create_pending(self, app, ctx):
        with app.app_context():
            ok, _, req = LeaveService.apply_leave(
                ctx["employee_id"], ctx["leave_type_id"],
                _today_plus(30), _today_plus(31)
            )
            assert ok
            return req.id

    def test_cancel_pending_succeeds(self, app, ctx):
        req_id = self._create_pending(app, ctx)
        with app.app_context():
            ok, code, req = LeaveService.cancel_leave(req_id, ctx["employee_id"])
            assert ok is True
            assert code == "SUCCESS"
            assert req.status == LeaveRequestStatus.CANCELLED

    def test_cancel_approved_blocked(self, app, ctx):
        req_id = self._create_pending(app, ctx)
        with app.app_context():
            LeaveService.approve_leave(req_id, ctx["hr_user_id"])
            ok, code, _ = LeaveService.cancel_leave(req_id, ctx["employee_id"])
            assert ok is False
            assert code == "NOT_PENDING"

    def test_cancel_wrong_employee_forbidden(self, app, ctx):
        req_id = self._create_pending(app, ctx)
        with app.app_context():
            ok, code, _ = LeaveService.cancel_leave(req_id, requesting_employee_id=99999)
            assert ok is False
            assert code == "FORBIDDEN"

    def test_cancel_already_cancelled_blocked(self, app, ctx):
        req_id = self._create_pending(app, ctx)
        with app.app_context():
            LeaveService.cancel_leave(req_id, ctx["employee_id"])
            ok, code, _ = LeaveService.cancel_leave(req_id, ctx["employee_id"])
            assert ok is False
            assert code == "NOT_PENDING"


# ---------------------------------------------------------------------------
# Tests: seed-demo-data CLI command (idempotency)
# ---------------------------------------------------------------------------

class TestSeedDemoData:

    def test_seed_demo_data_idempotent(self, app):
        """seed-demo-data must run twice without error or duplicate-key violation."""
        from click.testing import CliRunner
        runner = CliRunner()

        with app.app_context():
            # Retrieve the registered command from the app
            seed_cmd = app.cli.commands.get("seed-demo-data")
            assert seed_cmd is not None, "seed-demo-data command not registered"

            result1 = runner.invoke(seed_cmd, catch_exceptions=False)
            assert result1.exit_code == 0, f"First run failed:\n{result1.output}"

            result2 = runner.invoke(seed_cmd, catch_exceptions=False)
            assert result2.exit_code == 0, f"Second run failed:\n{result2.output}"

            # Verify no duplicate leave types were created
            count = LeaveType.query.count()
            assert count == 5, f"Expected 5 leave types, got {count}"
