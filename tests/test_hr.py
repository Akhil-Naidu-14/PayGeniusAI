import re
import pytest
from datetime import date
from decimal import Decimal
from werkzeug.security import generate_password_hash

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.department import Department
from models.employee import Employee, EmployeeStatus
from blueprints.auth.services import AuthService
from blueprints.hr.services import HRService

def get_csrf_token(client, path):
    response = client.get(path)
    html = response.data.decode("utf-8")
    match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    if not match:
        match = re.search(r'value="([^"]+)"[^>]+name="csrf_token"', html)
    return match.group(1) if match else None

def login_as(client, username_or_email, password):
    csrf_token = get_csrf_token(client, "/login")
    return client.post("/login", data={
        "csrf_token": csrf_token,
        "username_or_email": username_or_email,
        "password": password
    }, follow_redirects=True)


@pytest.fixture
def app():
    """Create and configure a clean testing app instance."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        # Seed core roles
        admin_role = Role(name=RoleType.ADMIN, description="Administrator Role")
        hr_role = Role(name=RoleType.HR, description="HR Role")
        emp_role = Role(name=RoleType.EMPLOYEE, description="Employee Role")
        db.session.add_all([admin_role, hr_role, emp_role])
        db.session.commit()

        # Seed default users
        admin_user = AuthService.create_user_by_admin(
            username="admin",
            email="admin@paygenius.ai",
            password="SecureAdminPassword@123",
            role_id=admin_role.id
        )
        hr_user = AuthService.create_user_by_admin(
            username="hr_manager",
            email="hr@paygenius.ai",
            password="SecureHRPassword@123",
            role_id=hr_role.id
        )
        emp_user = AuthService.create_user_by_admin(
            username="employee",
            email="employee@paygenius.ai",
            password="SecureEmpPassword@123",
            role_id=emp_role.id
        )
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


def test_access_controls(client, app):
    """Test access control rules on HR blueprint endpoints."""
    # 1. Anonymous user redirected to login
    response = client.get("/hr/departments", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    # 2. Employee role gets HTTP 403 Forbidden
    login_as(client, "employee", "SecureEmpPassword@123")
    response = client.get("/hr/departments")
    assert response.status_code == 403
    client.post("/logout", data={"csrf_token": get_csrf_token(client, "/")}, follow_redirects=True)

    # 3. HR Manager role successfully accesses listing
    login_as(client, "hr_manager", "SecureHRPassword@123")
    response = client.get("/hr/departments")
    assert response.status_code == 200
    client.post("/logout", data={"csrf_token": get_csrf_token(client, "/")}, follow_redirects=True)

    # 4. Administrator role successfully accesses listing
    login_as(client, "admin", "SecureAdminPassword@123")
    response = client.get("/hr/departments")
    assert response.status_code == 200


def test_department_crud_services(app):
    """Test Department CRUD Service methods and validations."""
    with app.app_context():
        # Create department
        dept = HRService.create_department(
            name="Engineering",
            code="ENG",
            description="Software Engineering department"
        )
        assert dept.id is not None
        assert dept.is_active is True

        # Prevent duplicate name
        with pytest.raises(ValueError) as excinfo:
            HRService.create_department(name="Engineering", code="OTHER")
        assert "name already exists" in str(excinfo.value)

        # Prevent duplicate code
        with pytest.raises(ValueError) as excinfo:
            HRService.create_department(name="Other Name", code="ENG")
        assert "code already exists" in str(excinfo.value)

        # Update department
        updated = HRService.update_department(
            dept_id=dept.id,
            data={"name": "Systems Engineering", "code": "SYS"}
        )
        assert updated.name == "Systems Engineering"
        assert updated.code == "SYS"

        # Soft Delete Department
        HRService.soft_delete_department(dept.id)
        assert dept.is_active is False

        # Attempting to fetch/update deleted department raises error
        with pytest.raises(ValueError):
            HRService.update_department(dept.id, {"name": "New Name"})


def test_soft_delete_department_safety_with_employees(app):
    """Test that a department cannot be soft deleted if it contains active employees."""
    with app.app_context():
        dept = HRService.create_department(name="Sales", code="SLS")
        
        # Provision active employee inside the department
        emp = HRService.create_employee({
            "employee_code": "SLS001",
            "first_name": "Sales",
            "last_name": "Guy",
            "email": "sales@paygenius.ai",
            "joining_date": date(2026, 1, 1),
            "employment_type": "Full-Time",
            "basic_salary": Decimal("54000.00"),
            "department_id": dept.id,
            "status": "Active"
        })

        # Attempt to delete department - should be blocked
        with pytest.raises(ValueError) as excinfo:
            HRService.soft_delete_department(dept.id)
        assert "active employees assigned" in str(excinfo.value)

        # Deactivate employee
        HRService.soft_delete_employee(emp.id)

        # Attempt delete again - should now succeed
        HRService.soft_delete_department(dept.id)
        assert dept.is_active is False


def test_employee_crud_services(app):
    """Test Employee CRUD Service operations and integrity rules."""
    with app.app_context():
        dept = HRService.create_department(name="Quality Assurance", code="QA")

        # Create Employee
        emp = HRService.create_employee({
            "employee_code": "QA101",
            "first_name": "John",
            "last_name": "Tester",
            "email": "john.tester@paygenius.ai",
            "joining_date": date(2026, 2, 1),
            "employment_type": "Contract",
            "basic_salary": Decimal("48000.00"),
            "department_id": dept.id,
            "status": "Active"
        })
        assert emp.id is not None
        assert emp.is_active is True

        # Enforce casing & email normalization
        assert emp.employee_code == "QA101"
        assert emp.email == "john.tester@paygenius.ai"

        # Prevent duplicate email
        with pytest.raises(ValueError) as excinfo:
            HRService.create_employee({
                "employee_code": "QA102",
                "first_name": "Another",
                "last_name": "Tester",
                "email": "JOHN.tester@paygenius.ai",
                "joining_date": date(2026, 2, 1),
                "employment_type": "Contract",
                "basic_salary": Decimal("48000.00"),
                "department_id": dept.id,
                "status": "Active"
            })
        assert "email address already exists" in str(excinfo.value)

        # Prevent duplicate employee_code
        with pytest.raises(ValueError) as excinfo:
            HRService.create_employee({
                "employee_code": "qa101",
                "first_name": "Another",
                "last_name": "Tester",
                "email": "other.tester@paygenius.ai",
                "joining_date": date(2026, 2, 1),
                "employment_type": "Contract",
                "basic_salary": Decimal("48000.00"),
                "department_id": dept.id,
                "status": "Active"
            })
        assert "employee code already exists" in str(excinfo.value)

        # Prevent registration under inactive department
        inactive_dept = HRService.create_department(name="Inactive Dept", code="INAC")
        HRService.soft_delete_department(inactive_dept.id)

        with pytest.raises(ValueError) as excinfo:
            HRService.create_employee({
                "employee_code": "INAC001",
                "first_name": "Bad",
                "last_name": "Dept",
                "email": "bad.dept@paygenius.ai",
                "joining_date": date(2026, 2, 1),
                "employment_type": "Contract",
                "basic_salary": Decimal("48000.00"),
                "department_id": inactive_dept.id,
                "status": "Active"
            })
        assert "inactive" in str(excinfo.value)

        # Validate status choices
        with pytest.raises(ValueError) as excinfo:
            HRService.create_employee({
                "employee_code": "QA999",
                "first_name": "Bad",
                "last_name": "Status",
                "email": "bad.status@paygenius.ai",
                "joining_date": date(2026, 2, 1),
                "employment_type": "Contract",
                "basic_salary": Decimal("48000.00"),
                "department_id": dept.id,
                "status": "Terminated"  # Invalid status choice
            })
        assert "Invalid employee status" in str(excinfo.value)

        # Update Employee
        updated = HRService.update_employee(emp.id, {
            "first_name": "Johnny",
            "basic_salary": Decimal("54006.00")
        })
        assert updated.first_name == "Johnny"
        assert updated.basic_salary == Decimal("54006.00")

        # Soft Delete Employee
        HRService.soft_delete_employee(emp.id)
        assert emp.is_active is False


def test_listings_exclude_soft_deleted_records(app):
    """Verify list queries strictly return active records (is_active == True) only."""
    with app.app_context():
        # Setup active departments
        dept_active = HRService.create_department(name="Active Dept", code="ACT")
        dept_deleted = HRService.create_department(name="Deleted Dept", code="DEL")
        HRService.soft_delete_department(dept_deleted.id)

        # Setup active/deleted employees
        emp_active = HRService.create_employee({
            "employee_code": "ACT001",
            "first_name": "Active",
            "last_name": "Employee",
            "email": "active@paygenius.ai",
            "joining_date": date(2026, 1, 1),
            "employment_type": "Full-Time",
            "basic_salary": Decimal("60000.00"),
            "department_id": dept_active.id,
            "status": "Active"
        })
        emp_deleted = HRService.create_employee({
            "employee_code": "DEL001",
            "first_name": "Deleted",
            "last_name": "Employee",
            "email": "deleted@paygenius.ai",
            "joining_date": date(2026, 1, 1),
            "employment_type": "Full-Time",
            "basic_salary": Decimal("60000.00"),
            "department_id": dept_active.id,
            "status": "Active"
        })
        HRService.soft_delete_employee(emp_deleted.id)

        # Verify department list ignores soft-deleted
        departments = HRService.list_departments()
        assert dept_active in departments
        assert dept_deleted not in departments

        # Verify employee list ignores soft-deleted
        emp_pagination = HRService.list_employees()
        active_ids = [e.id for e in emp_pagination.items]
        assert emp_active.id in active_ids
        assert emp_deleted.id not in active_ids
