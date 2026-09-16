import re
import json
import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.department import Department
from models.employee import Employee, EmployeeStatus
from models.payroll import Payroll
from models.ai_conversation import AIConversation
from models.government_rule import GovernmentRule
from blueprints.auth.services import AuthService
from blueprints.ai.services import AIService

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


class TestAIService:

    @patch("blueprints.ai.services.requests.post")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake-api-key"})
    def test_gemini_analysis_success(self, mock_post, app, ctx):
        # Configure mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "summary": "Test Summary Explanation",
                            "risk_rating": "Medium",
                            "compliance_status": "FAIL",
                            "recommendation": "Test Recommendation Action",
                            "anomaly_reasons": ["Salary spike detected"],
                            "government_violations": ["[MINIMUM_WAGE] Underpaid"]
                        })
                    }]
                }
            }]
        }
        mock_post.return_value = mock_response

        with app.app_context():
            # Seed minimum wage rule of 50,000 (payroll at 48,000 will fail)
            rule = GovernmentRule(
                rule_type="MINIMUM_WAGE",
                value=Decimal("50000.00"),
                effective_from=date(2026, 8, 1),
                is_active=True
            )
            db.session.add(rule)
            db.session.commit()

            # Seed payroll
            payroll = Payroll(
                employee_id=ctx["employee_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("48000.00")
            )
            db.session.add(payroll)
            db.session.commit()

            res = AIService.generate_payroll_analysis(
                employee_id=ctx["employee_id"],
                month=8,
                year=2026,
                user_id=ctx["admin_user_id"]
            )

            # Assert structured response formatting
            assert res["summary"] == "Test Summary Explanation"
            assert res["recommendation"] == "Test Recommendation Action"
            assert res["risk_rating"] == "Medium"
            assert res["compliance_status"] == "FAIL"
            assert "Salary spike detected" in res["anomaly_reasons"]
            assert "[MINIMUM_WAGE] Underpaid" in res["government_violations"]

            # Verify Prompt contains compliance messages
            called_args, called_kwargs = mock_post.call_args
            prompt_payload = called_kwargs["json"]["contents"][0]["parts"][0]["text"]
            assert "Alice Smith" in prompt_payload
            assert "48,000.00" in prompt_payload
            assert "Compliance" in prompt_payload

            # Assert conversation logged in database
            convo = AIConversation.query.filter_by(
                user_id=ctx["admin_user_id"],
                employee_id=ctx["employee_id"]
            ).first()
            assert convo is not None
            assert "Alice Smith" in convo.prompt
            
            logged_res = json.loads(convo.response)
            assert logged_res["summary"] == "Test Summary Explanation"
            assert logged_res["risk_rating"] == "Medium"

    @patch("blueprints.ai.services.requests.post")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake-api-key"})
    def test_gemini_analysis_fallback_on_api_failure(self, mock_post, app, ctx):
        # Configure mock response for error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        with app.app_context():
            # Seed payroll
            payroll = Payroll(
                employee_id=ctx["employee_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("48000.00")
            )
            db.session.add(payroll)
            db.session.commit()

            res = AIService.generate_payroll_analysis(
                employee_id=ctx["employee_id"],
                month=8,
                year=2026,
                user_id=ctx["admin_user_id"]
            )

            # Check that fallback message was returned instead of raising exception
            assert "temporarily unavailable" in res["summary"]
            assert "manually review" in res["recommendation"]
            assert res["risk_rating"] == "None"
            assert res["compliance_status"] == "PASS"

            # Conversation logged in database even for fallback
            convo = AIConversation.query.filter_by(
                user_id=ctx["admin_user_id"],
                employee_id=ctx["employee_id"]
            ).first()
            assert convo is not None


class TestAIRoutes:

    @patch("blueprints.ai.services.requests.post")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake-api-key"})
    def test_analysis_route_access_control(self, mock_post, client, app, ctx):
        # Configure mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "summary": "Test Summary",
                            "risk_rating": "Low",
                            "compliance_status": "PASS",
                            "recommendation": "Test Action",
                            "anomaly_reasons": [],
                            "government_violations": []
                        })
                    }]
                }
            }]
        }
        mock_post.return_value = mock_response

        # Seed payroll
        with app.app_context():
            payroll = Payroll(
                employee_id=ctx["employee_id"],
                month=8,
                year=2026,
                basic_salary=Decimal("48000.00"),
                gross_salary=Decimal("48000.00"),
                total_deductions=Decimal("0.00"),
                net_salary=Decimal("48000.00")
            )
            db.session.add(payroll)
            db.session.commit()

        # 1. Anonymous gets redirected/blocked (302)
        resp1 = client.get(f"/payroll/{ctx['employee_id']}/8/2026/analysis")
        assert resp1.status_code == 302

        # 2. Logged in regular employee gets forbidden (403)
        login_as(client, "emp1@paygenius.ai", "Emp@123451")
        resp2 = client.get(f"/payroll/{ctx['employee_id']}/8/2026/analysis")
        assert resp2.status_code == 403

        # 3. Logged in Admin succeeds (200)
        login_as(client, "admin@paygenius.ai", "Admin@12345")
        resp3 = client.get(f"/payroll/{ctx['employee_id']}/8/2026/analysis")
        assert resp3.status_code == 200
        assert resp3.json["success"] is True
        assert resp3.json["data"]["summary"] == "Test Summary"
        assert resp3.json["data"]["risk_rating"] == "Low"
        assert resp3.json["data"]["compliance_status"] == "PASS"
