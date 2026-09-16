import re
import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from blueprints.auth.services import AuthService

# Regular expression helper to extract the Flask-WTF CSRF token from rendered HTML pages.
def get_csrf_token(client, path):
    response = client.get(path)
    html = response.data.decode("utf-8")
    match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    if not match:
        match = re.search(r'value="([^"]+)"[^>]+name="csrf_token"', html)
    return match.group(1) if match else None


@pytest.fixture
def app():
    """Create and configure a clean testing app instance."""
    app = create_app("testing")
    
    # Establish application context
    with app.app_context():
        db.create_all()
        
        # Seed core roles
        admin_role = Role(name=RoleType.ADMIN, description="Administrator Role")
        hr_role = Role(name=RoleType.HR, description="HR Role")
        emp_role = Role(name=RoleType.EMPLOYEE, description="Employee Role")
        inactive_role = Role(name="InactiveRole", description="Inactive Role", is_active=False)
        
        db.session.add_all([admin_role, hr_role, emp_role, inactive_role])
        db.session.commit()
        
        # Seed default users
        # 1. Administrator
        admin_user = AuthService.create_user_by_admin(
            username="admin",
            email="admin@paygenius.ai",
            password="SecureAdminPassword@123",
            role_id=admin_role.id
        )
        # 2. HR Manager
        hr_user = AuthService.create_user_by_admin(
            username="hr_manager",
            email="hr@paygenius.ai",
            password="SecureHRPassword@123",
            role_id=hr_role.id
        )
        # 3. Employee
        emp_user = AuthService.create_user_by_admin(
            username="employee",
            email="employee@paygenius.ai",
            password="SecureEmpPassword@123",
            role_id=emp_role.id
        )
        # 4. Inactive Employee
        inactive_user = AuthService.create_user_by_admin(
            username="inactive_emp",
            email="inactive@paygenius.ai",
            password="SecureInactivePassword@123",
            role_id=emp_role.id
        )
        inactive_user.is_active = False
        
        # 5. Inactive Role Employee (seed directly to bypass role active validations in AuthService)
        inactive_role_user = User(
            username="inactive_role_emp",
            email="inactiverole@paygenius.ai",
            password_hash=generate_password_hash("SecureInactiveRolePassword@123"),
            role_id=inactive_role.id
        )
        db.session.add(inactive_role_user)
        db.session.commit()
        
    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()



@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


def test_successful_admin_login(client, app):
    """Test successful login using admin username."""
    with app.app_context():
        csrf_token = get_csrf_token(client, "/login")
        response = client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"You have successfully logged in." in response.data
        
        # Verify user is logged in via session
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is not None


def test_login_using_email(client, app):
    """Test successful login using admin email."""
    with app.app_context():
        csrf_token = get_csrf_token(client, "/login")
        response = client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin@paygenius.ai",
            "password": "SecureAdminPassword@123"
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"You have successfully logged in." in response.data
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is not None


def test_invalid_password(client, app):
    """Test login failure on incorrect password."""
    with app.app_context():
        csrf_token = get_csrf_token(client, "/login")
        response = client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "WrongPassword@99"
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"Invalid username/email or password." in response.data
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is None


def test_inactive_user_login_rejection(client, app):
    """Test login rejection for inactive user accounts."""
    with app.app_context():
        csrf_token = get_csrf_token(client, "/login")
        response = client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "inactive_emp",
            "password": "SecureInactivePassword@123"
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"Invalid username/email or password." in response.data
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is None


def test_inactive_role_login_rejection(client, app):
    """Test login rejection for users with inactive privilege roles."""
    with app.app_context():
        csrf_token = get_csrf_token(client, "/login")
        response = client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "inactive_role_emp",
            "password": "SecureInactiveRolePassword@123"
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"Invalid username/email or password." in response.data
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is None


def test_logout_post_success(client, app):
    """Test logging out succeeds using a POST request."""
    with app.app_context():
        # First log in
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is not None
        
        # Logout via POST (including csrf)
        logout_csrf = get_csrf_token(client, "/")
        response = client.post("/logout", data={
            "csrf_token": logout_csrf
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"You have been logged out." in response.data
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is None


def test_logout_get_rejected(client, app):
    """Test logout GET requests return a 405 Method Not Allowed error."""
    with app.app_context():
        # First log in
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is not None
        
        # Try logout via GET
        response = client.get("/logout")
        assert response.status_code == 405


def test_anonymous_create_user_redirects(client, app):
    """Test anonymous request accessing admin routes gets redirected to login."""
    with app.app_context():
        response = client.get("/admin/create-user")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


def test_employee_create_user_returns_403(client, app):
    """Test employee access to administrative user creation returns 403 Forbidden."""
    with app.app_context():
        # Log in as employee
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "employee",
            "password": "SecureEmpPassword@123"
        })
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is not None
        
        # Access admin route
        response = client.get("/admin/create-user")
        assert response.status_code == 403


def test_admin_creates_hr_user(client, app):
    """Test Administrator creates new HR user account successfully."""
    with app.app_context():
        # Login as admin
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        with client.session_transaction() as sess:
            assert sess.get("_user_id") is not None
        
        # Fetch create-user form csrf
        create_csrf = get_csrf_token(client, "/admin/create-user")
        
        # Get HR role ID
        hr_role = Role.query.filter_by(name=RoleType.HR).first()
        
        # Create new user
        response = client.post("/admin/create-user", data={
            "csrf_token": create_csrf,
            "username": "new_hr_guy",
            "email": "new_hr@paygenius.ai",
            "password": "HrPassword@555",
            "confirm_password": "HrPassword@555",
            "role_id": hr_role.id
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"User account" in response.data
        assert b"new_hr_guy" in response.data
        assert b"successfully created" in response.data
        
        # Confirm user is in database
        new_user = User.query.filter_by(username="new_hr_guy").first()
        assert new_user is not None
        assert new_user.email == "new_hr@paygenius.ai"
        assert new_user.role.name == RoleType.HR


def test_duplicate_username_rejected(client, app):
    """Test duplicate username registration is rejected."""
    with app.app_context():
        # Login as admin
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        create_csrf = get_csrf_token(client, "/admin/create-user")
        hr_role = Role.query.filter_by(name=RoleType.HR).first()
        
        # Attempt to create user with existing username "employee"
        response = client.post("/admin/create-user", data={
            "csrf_token": create_csrf,
            "username": "employee",  # Already exists
            "email": "unique_email@paygenius.ai",
            "password": "SomePassword@123",
            "confirm_password": "SomePassword@123",
            "role_id": hr_role.id
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"Username is already in use." in response.data or b"validation errors" in response.data


def test_duplicate_email_rejected(client, app):
    """Test duplicate email registration is rejected."""
    with app.app_context():
        # Login as admin
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        create_csrf = get_csrf_token(client, "/admin/create-user")
        hr_role = Role.query.filter_by(name=RoleType.HR).first()
        
        # Attempt to create user with existing email "employee@paygenius.ai"
        response = client.post("/admin/create-user", data={
            "csrf_token": create_csrf,
            "username": "unique_username",
            "email": "employee@paygenius.ai",  # Already exists
            "password": "SomePassword@123",
            "confirm_password": "SomePassword@123",
            "role_id": hr_role.id
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b"Email address is already in use." in response.data or b"validation errors" in response.data


def test_invalid_role_rejected(client, app):
    """Test user creation fails when assigning a non-existent role ID."""
    with app.app_context():
        # Login as admin
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        create_csrf = get_csrf_token(client, "/admin/create-user")
        
        # Post with a non-existent role ID (e.g. 9999)
        response = client.post("/admin/create-user", data={
            "csrf_token": create_csrf,
            "username": "valid_user",
            "email": "valid_email@paygenius.ai",
            "password": "SomePassword@123",
            "confirm_password": "SomePassword@123",
            "role_id": 9999  # Invalid role
        }, follow_redirects=True)
        
        # The form validates choices dynamically, so it will reject 9999 as an invalid choice
        assert response.status_code == 200
        assert b"Not a valid choice" in response.data or b"validation errors" in response.data or b"Selected role" in response.data


def test_external_next_url_rejected(client, app):
    """Test external next parameters are rejected to prevent open redirects."""
    with app.app_context():
        csrf_token = get_csrf_token(client, "/login")
        response = client.post("/login?next=http://attacker.com", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        
        # Safe redirection should send the client to the index page instead of attacker.com
        assert response.status_code == 302
        assert response.headers["Location"] in ["/dashboard", "http://localhost/dashboard"]


def test_csrf_protection_on_post_routes(client, app):
    """Test that POST requests without CSRF tokens are rejected with a 400 Bad Request."""
    with app.app_context():
        response = client.post("/login", data={
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })
        assert response.status_code == 400
        assert b"The CSRF token is missing." in response.data


def test_self_change_password_complexity_and_rules(client, app, caplog):
    """Test self password change validators (complexity, similarity, reuse, success)."""
    with app.app_context():
        # Login
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "employee",
            "password": "SecureEmpPassword@123"
        })
        
        # Get change password token
        change_csrf = get_csrf_token(client, "/auth/change-password")


        
        # 1. Weak password (no uppercase)
        response = client.post("/auth/change-password", data={
            "csrf_token": change_csrf,
            "current_password": "SecureEmpPassword@123",
            "new_password": "weakpassword123",
            "confirm_password": "weakpassword123"
        }, follow_redirects=True)
        assert b"Password must be at least 8 characters" in response.data
        assert "PASSWORD_CHANGE_FAILURE" in caplog.text

        # 2. Reuse current password
        response = client.post("/auth/change-password", data={
            "csrf_token": change_csrf,
            "current_password": "SecureEmpPassword@123",
            "new_password": "SecureEmpPassword@123",
            "confirm_password": "SecureEmpPassword@123"
        }, follow_redirects=True)
        assert b"New password cannot be the same" in response.data

        # 3. Username similarity
        response = client.post("/auth/change-password", data={
            "csrf_token": change_csrf,
            "current_password": "SecureEmpPassword@123",
            "new_password": "employee",
            "confirm_password": "employee"
        }, follow_redirects=True)
        assert b"New password cannot be equal to your username" in response.data

        # 4. Email similarity (local part is 'employee')
        response = client.post("/auth/change-password", data={
            "csrf_token": change_csrf,
            "current_password": "SecureEmpPassword@123",
            "new_password": "employee",
            "confirm_password": "employee"
        }, follow_redirects=True)
        assert b"New password cannot be equal to your username" in response.data # matches username check first

        # 5. Success self change forces logout & session clear
        caplog.clear()
        response = client.post("/auth/change-password", data={
            "csrf_token": change_csrf,
            "current_password": "SecureEmpPassword@123",
            "new_password": "BrandNewSecurePassword@999",
            "confirm_password": "BrandNewSecurePassword@999"
        }, follow_redirects=True)
        assert b"Password changed successfully. Please log in again." in response.data
        assert "PASSWORD_CHANGE_SUCCESS" in caplog.text
        
        # Verify user is logged out (redirects to login)
        logout_check = client.get("/auth/change-password")
        assert logout_check.status_code == 302
            
        # Re-login with old password fails
        from flask import g
        if hasattr(g, "csrf_token"):
            delattr(g, "csrf_token")
        client._cookies.clear()
        csrf_token = get_csrf_token(client, "/login")
        login_res = client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "employee",
            "password": "SecureEmpPassword@123"
        }, follow_redirects=True)
        assert b"Invalid username/email or password" in login_res.data










def test_admin_reset_password_security(client, app, caplog):
    """Test admin password reset endpoints and constraints (success, 403 self reset, inactive user, enumeration)."""
    with app.app_context():
        # Get target user (HR manager has ID 2 in seeds)
        target_user = User.query.filter_by(username="hr_manager").first()
        target_id = target_user.id

        # 1. Anonymous / Employee gets rejected
        response = client.get(f"/auth/reset-password/{target_id}")
        assert response.status_code == 302 # Redirect to login

        # Login as Admin
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })

        # 2. Admin cannot reset own password -> returns 403
        admin_user = User.query.filter_by(username="admin").first()
        self_reset_res = client.get(f"/auth/reset-password/{admin_user.id}")
        assert self_reset_res.status_code == 403

        # 3. Successful admin reset (target user password)
        reset_csrf = get_csrf_token(client, f"/auth/reset-password/{target_id}")
        caplog.clear()
        success_res = client.post(f"/auth/reset-password/{target_id}", data={
            "csrf_token": reset_csrf,
            "new_password": "NewHrPassword@777",
            "confirm_password": "NewHrPassword@777"
        }, follow_redirects=True)
        assert success_res.status_code == 200
        assert b"Password reset request processed." in success_res.data
        assert "PASSWORD_RESET_SUCCESS" in caplog.text

        # 4. Inactive user reset blocked
        inactive_user = User.query.filter_by(username="inactive_emp").first()
        caplog.clear()
        inactive_csrf = get_csrf_token(client, f"/auth/reset-password/{inactive_user.id}")
        inactive_res = client.post(f"/auth/reset-password/{inactive_user.id}", data={
            "csrf_token": inactive_csrf,
            "new_password": "SomeValidPassword@888",
            "confirm_password": "SomeValidPassword@888"
        }, follow_redirects=True)
        assert inactive_res.status_code == 200
        # Returns generic success message (enumeration protection)
        assert b"Password reset request processed." in inactive_res.data
        assert "PASSWORD_RESET_FAILURE" in caplog.text

        # 5. Non-existent user ID reset check (enumeration safety)
        caplog.clear()
        non_existent_csrf = get_csrf_token(client, "/auth/reset-password/999")
        non_existent_res = client.post("/auth/reset-password/999", data={
            "csrf_token": non_existent_csrf,
            "new_password": "SomeValidPassword@888",
            "confirm_password": "SomeValidPassword@888"
        }, follow_redirects=True)
        assert non_existent_res.status_code == 200
        assert b"Password reset request processed." in non_existent_res.data
        assert "PASSWORD_RESET_FAILURE" in caplog.text


def test_link_to_employee_user_creation(client, app):
    """Test creating user and linking to active employee optionally, including dropdown lists and validations."""
    from models.employee import Employee
    from models.department import Department
    from datetime import date
    from decimal import Decimal

    with app.app_context():
        # 1. Seed a new active department and employees
        dept = Department(name="Test Dept Link", code="TDLINK")
        db.session.add(dept)
        db.session.commit()
        
        emp1 = Employee(
            employee_code="TEST_EMP_LINK_1",
            first_name="LinkOne",
            last_name="Test",
            email="link1@paygenius.ai",
            joining_date=date(2026, 1, 1),
            employment_type="Full-Time",
            basic_salary=Decimal("360000.00"),
            department_id=dept.id,
            status="Active"
        )
        emp2 = Employee(
            employee_code="TEST_EMP_LINK_2",
            first_name="LinkTwo",
            last_name="Test",
            email="link2@paygenius.ai",
            joining_date=date(2026, 1, 1),
            employment_type="Full-Time",
            basic_salary=Decimal("360000.00"),
            department_id=dept.id,
            status="Active"
        )
        db.session.add_all([emp1, emp2])
        db.session.commit()
        
        emp1_id = emp1.id
        emp2_id = emp2.id

        # Login as Admin
        csrf_token = get_csrf_token(client, "/login")
        client.post("/login", data={
            "csrf_token": csrf_token,
            "username_or_email": "admin",
            "password": "SecureAdminPassword@123"
        })

        # 2. GET create-user page to verify dropdown choices render
        create_res = client.get("/admin/create-user")
        assert create_res.status_code == 200
        html = create_res.data.decode("utf-8")
        assert "Link to Employee" in html
        assert "TEST_EMP_LINK_1" in html
        assert "TEST_EMP_LINK_2" in html

        # 3. Create a User linked to emp1
        create_csrf = get_csrf_token(client, "/admin/create-user")
        hr_role = Role.query.filter_by(name=RoleType.HR).first()
        
        link_res = client.post("/admin/create-user", data={
            "csrf_token": create_csrf,
            "username": "linked_user_1",
            "email": "linked_user_1@paygenius.ai",
            "password": "LinkedPassword@123",
            "confirm_password": "LinkedPassword@123",
            "role_id": hr_role.id,
            "employee_id": emp1_id
        }, follow_redirects=True)
        assert link_res.status_code == 200
        
        # Verify db linkage
        u1 = User.query.filter_by(username="linked_user_1").first()
        assert u1 is not None
        assert u1.employee_id == emp1_id
        assert u1.employee.employee_code == "TEST_EMP_LINK_1"

        # 4. GET create-user page again and verify emp1 no longer appears in choices
        create_res2 = client.get("/admin/create-user")
        html2 = create_res2.data.decode("utf-8")
        assert "TEST_EMP_LINK_1" not in html2
        assert "TEST_EMP_LINK_2" in html2

        # 5. Try to link another user to emp1 (should be blocked by WTForms validation first)
        create_csrf2 = get_csrf_token(client, "/admin/create-user")
        duplicate_link_res = client.post("/admin/create-user", data={
            "csrf_token": create_csrf2,
            "username": "linked_user_2",
            "email": "linked_user_2@paygenius.ai",
            "password": "LinkedPassword@123",
            "confirm_password": "LinkedPassword@123",
            "role_id": hr_role.id,
            "employee_id": emp1_id
        }, follow_redirects=True)
        assert duplicate_link_res.status_code == 200
        assert b"Not a valid choice" in duplicate_link_res.data

        # 6. Verify service layer directly raises ValueError if bypassed
        with pytest.raises(ValueError) as exc:
            AuthService.create_user_by_admin(
                username="linked_user_3",
                email="linked_user_3@paygenius.ai",
                password="LinkedPassword@123",
                role_id=hr_role.id,
                employee_id=emp1_id
            )
        assert "already linked" in str(exc.value)





