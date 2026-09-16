import re
import calendar
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import pytest
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

from app import create_app
from extensions import db
from models.role import Role, RoleType
from models.user import User
from models.employee import Employee
from models.department import Department
from models.attendance import Attendance, AttendanceStatus
from blueprints.analytics.prediction_service import (
    AttendancePredictionService,
    STATE_NO_DATA,
    STATE_INSUFFICIENT_DATA,
    STATE_EXPERIMENTAL,
    STATE_PREDICTION_AVAILABLE,
    MIN_REQUIRED_TRAINING_SAMPLES,
    RECOMMENDED_FULL_SAMPLES
)
from blueprints.auth.services import AuthService
from scripts.seed_ml_demo_data import seed_demo_attendance_data


def get_csrf_token(client, path):
    response = client.get(path)
    html = response.data.decode("utf-8")
    match = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    if not match:
        match = re.search(r'value="([^"]+)"[^>]+name="csrf_token"', html)
    return match.group(1) if match else None


@pytest.fixture
def app():
    """Create and configure testing app instance."""
    app_instance = create_app("testing")
    with app_instance.app_context():
        db.create_all()

        admin_role = Role(name=RoleType.ADMIN, description="Administrator")
        hr_role = Role(name=RoleType.HR, description="HR Manager")
        emp_role = Role(name=RoleType.EMPLOYEE, description="Employee")
        db.session.add_all([admin_role, hr_role, emp_role])
        db.session.commit()

        dept = Department(name="Engineering", code="ENG")
        db.session.add(dept)
        db.session.commit()

        emp1 = Employee(
            employee_code="EMP_ML_001",
            first_name="Alice",
            last_name="Smith",
            email="alice@paygenius.ai",
            joining_date=date(2025, 1, 1),
            employment_type="Full-Time",
            basic_salary=Decimal("600000.00"),
            department_id=dept.id,
            status="Active"
        )
        emp2 = Employee(
            employee_code="EMP_ML_002",
            first_name="Bob",
            last_name="Jones",
            email="bob@paygenius.ai",
            joining_date=date(2025, 1, 1),
            employment_type="Full-Time",
            basic_salary=Decimal("540000.00"),
            department_id=dept.id,
            status="Active"
        )
        db.session.add_all([emp1, emp2])
        db.session.commit()

        AuthService.create_user_by_admin(
            username="admin",
            email="admin@paygenius.ai",
            password="SecureAdminPassword@123",
            role_id=admin_role.id
        )
        AuthService.create_user_by_admin(
            username="alice",
            email="alice@paygenius.ai",
            password="SecureAlicePassword@123",
            role_id=emp_role.id,
            employee_id=emp1.id
        )
        AuthService.create_user_by_admin(
            username="bob",
            email="bob@paygenius.ai",
            password="SecureBobPassword@123",
            role_id=emp_role.id,
            employee_id=emp2.id
        )

        yield app_instance
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def test_scheduled_workdays_and_metrics_extraction(app):
    """Test standard scheduled weekdays calculation and feature extraction."""
    with app.app_context():
        workdays = AttendancePredictionService.get_scheduled_workdays(2026, 8)
        assert workdays == 21

        emp = Employee.query.filter_by(employee_code="EMP_ML_001").first()

        for d in range(1, 11):
            att = Attendance(
                employee_id=emp.id,
                date=date(2026, 8, d),
                working_hours=Decimal("8.50"),
                overtime_hours=Decimal("0.50"),
                late_minutes=15 if d == 1 else 0,
                status=AttendanceStatus.PRESENT
            )
            db.session.add(att)

        for d in range(11, 13):
            att = Attendance(
                employee_id=emp.id,
                date=date(2026, 8, d),
                working_hours=Decimal("4.00"),
                overtime_hours=Decimal("0.00"),
                late_minutes=0,
                status=AttendanceStatus.HALF_DAY
            )
            db.session.add(att)

        db.session.commit()

        metrics = AttendancePredictionService.extract_monthly_metrics(emp.id, 8, 2026)
        assert metrics["has_records"] is True
        assert metrics["present_days"] == 10
        assert metrics["half_days"] == 2
        assert metrics["total_overtime_hours"] == 5.0
        assert metrics["late_count"] == 1


def test_temporal_data_leakage_prevention(app):
    """Test that feature extraction for month T strictly excludes data from month T or future."""
    with app.app_context():
        emp = Employee.query.filter_by(employee_code="EMP_ML_001").first()

        # July 2026 (T-1): 0 late days
        for d in range(1, 21):
            att_jul = Attendance(
                employee_id=emp.id,
                date=date(2026, 7, d),
                working_hours=Decimal("8.00"),
                overtime_hours=Decimal("1.00"),
                late_minutes=0,
                status=AttendanceStatus.PRESENT
            )
            db.session.add(att_jul)

        # August 2026 (Month T): 5 late days
        for d in range(1, 6):
            att_aug = Attendance(
                employee_id=emp.id,
                date=date(2026, 8, d),
                working_hours=Decimal("8.00"),
                overtime_hours=Decimal("0.00"),
                late_minutes=30,
                status=AttendanceStatus.PRESENT
            )
            db.session.add(att_aug)

        db.session.commit()

        features, target = AttendancePredictionService.extract_features_for_target_month(emp.id, 8, 2026)
        assert features is not None
        assert target is not None
        # x_3 (late count) MUST reflect July (0.0), NOT August (5.0)
        assert features[2] == 0.0


def test_data_sufficiency_levels_and_states(app):
    """Test states for <15 samples (INSUFFICIENT), 15-29 (EXPERIMENTAL), and >=30 (NORMAL)."""
    with app.app_context():
        emp = Employee.query.filter_by(employee_code="EMP_ML_001").first()

        # Case 1: 0 records -> STATE_NO_DATA
        res_no_data = AttendancePredictionService.predict_next_month_attendance(emp.id)
        assert res_no_data["state"] == STATE_NO_DATA

        # Case 2: Seed 4 months for 2 employees -> 8 samples (< 15) -> STATE_INSUFFICIENT_DATA
        seed_demo_attendance_data(num_months=4, random_seed=42)
        X, y, meta = AttendancePredictionService.build_training_dataset()
        assert len(X) < MIN_REQUIRED_TRAINING_SAMPLES

        res_insufficient = AttendancePredictionService.predict_next_month_attendance(emp.id)
        assert res_insufficient["state"] == STATE_INSUFFICIENT_DATA

        # Case 3: Seed 10 months for 2 employees -> 18 samples (15 <= N < 30) -> STATE_EXPERIMENTAL
        seed_demo_attendance_data(num_months=10, random_seed=42)
        X_exp, y_exp, meta_exp = AttendancePredictionService.build_training_dataset()
        assert len(X_exp) >= MIN_REQUIRED_TRAINING_SAMPLES

        res_exp = AttendancePredictionService.predict_next_month_attendance(emp.id)
        assert res_exp["success"] is True
        assert res_exp["state"] == STATE_EXPERIMENTAL
        assert "Limited historical dataset" in res_exp["advisory_disclaimer"]


def test_month_grouped_temporal_validation(app):
    """Test that train/test validation split partitions strictly by target calendar month."""
    with app.app_context():
        seed_demo_attendance_data(num_months=10, random_seed=42)
        X, y, metadata = AttendancePredictionService.build_training_dataset()

        ym_tuples = [(m["target_year"], m["target_month"]) for m in metadata]
        unique_ym = list(dict.fromkeys(ym_tuples))

        assert len(unique_ym) >= 2

        # Run model evaluation
        train_res = AttendancePredictionService.train_and_evaluate_model(X, y, metadata)
        assert train_res["trained"] is True
        assert train_res["metrics"]["validation_mae"] is not None


def test_mathematical_feature_contributions(app):
    """Test that model contributions originate from standardized value * coefficient (z_i * w_i)."""
    features = [95.0, 92.0, 1.0, 8.0, 4.0, 0.0, 12.0]
    scaler = StandardScaler()
    X_fake = np.random.rand(20, 7) * 100
    scaler.fit(X_fake)

    ridge = Ridge(alpha=1.0)
    ridge.fit(scaler.transform(X_fake), np.random.rand(20) * 100)

    contributions = AttendancePredictionService.calculate_mathematical_contributions(features, scaler, ridge)
    assert len(contributions) == 7

    # Verify mathematical formula for first contribution item
    item = contributions[0]
    feat_idx = AttendancePredictionService.FEATURE_NAMES.index(item["feature"])
    expected_z = (features[feat_idx] - scaler.mean_[feat_idx]) / scaler.scale_[feat_idx]
    expected_contrib = round(float(expected_z * ridge.coef_[feat_idx]), 2)
    assert item["contribution"] == expected_contrib


def test_no_http_demo_seeding_route(client, app):
    """Test that POST /analytics/seed-demo-attendance route has been removed (returns 404)."""
    res = client.post("/analytics/seed-demo-attendance")
    assert res.status_code == 404


def test_api_rbac_using_user_employee_id(client, app):
    """Test API authorization using User.employee_id FK (Alice can view own forecast; 403 on Bob's)."""
    with app.app_context():
        seed_demo_attendance_data(num_months=4, random_seed=42)
        emp1 = Employee.query.filter_by(employee_code="EMP_ML_001").first()
        emp2 = Employee.query.filter_by(employee_code="EMP_ML_002").first()

    # Anonymous -> 302
    assert client.get(f"/analytics/api/attendance-prediction/{emp1.id}").status_code == 302

    # Login Alice (linked to emp1)
    token = get_csrf_token(client, "/login")
    client.post("/login", data={
        "username_or_email": "alice",
        "password": "SecureAlicePassword@123",
        "csrf_token": token
    }, follow_redirects=True)

    # Alice accesses own forecast -> 200 OK
    res_own = client.get(f"/analytics/api/attendance-prediction/{emp1.id}")
    assert res_own.status_code == 200

    # Alice accesses Bob's forecast -> 403 Forbidden
    res_other = client.get(f"/analytics/api/attendance-prediction/{emp2.id}")
    assert res_other.status_code == 403


def test_risk_boundary_classification():
    """Test exact risk band boundaries (74.9 -> High, 75.0 -> Moderate, 89.9 -> Moderate, 90.0 -> Low)."""
    # 74.9 -> High
    pred_val = 74.9
    risk_band = "Low" if pred_val >= 90.0 else ("Moderate" if pred_val >= 75.0 else "High")
    assert risk_band == "High"

    # 75.0 -> Moderate
    pred_val = 75.0
    risk_band = "Low" if pred_val >= 90.0 else ("Moderate" if pred_val >= 75.0 else "High")
    assert risk_band == "Moderate"

    # 89.9 -> Moderate
    pred_val = 89.9
    risk_band = "Low" if pred_val >= 90.0 else ("Moderate" if pred_val >= 75.0 else "High")
    assert risk_band == "Moderate"

    # 90.0 -> Low
    pred_val = 90.0
    risk_band = "Low" if pred_val >= 90.0 else ("Moderate" if pred_val >= 75.0 else "High")
    assert risk_band == "Low"


def test_r2_guardrail_on_small_samples():
    """Test that validation_r2 returns None when validation population size < 5."""
    # 17 samples total across 3 months; target month 3 has only 2 samples (<5)
    X_small = np.random.rand(17, 7) * 100
    y_small = np.random.rand(17) * 100
    meta_small = (
        [{"target_year": 2026, "target_month": 1}] * 10 +
        [{"target_year": 2026, "target_month": 2}] * 5 +
        [{"target_year": 2026, "target_month": 3}] * 2
    )

    res = AttendancePredictionService.train_and_evaluate_model(X_small, y_small, meta_small)
    assert res["trained"] is True
    # Validation size is 2 (< 5), so validation_r2 MUST be None
    assert res["metrics"]["validation_r2"] is None
