import calendar
import logging
from datetime import date
from decimal import Decimal

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score

from extensions import db
from models.attendance import Attendance, AttendanceStatus
from models.employee import Employee
from blueprints.payroll.services import PayrollService

logger = logging.getLogger(__name__)

# Explicit data sufficiency states
STATE_NO_DATA = "NO_DATA"
STATE_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATE_EXPERIMENTAL = "EXPERIMENTAL"
STATE_PREDICTION_AVAILABLE = "PREDICTION_AVAILABLE"
STATE_PREDICTION_ERROR = "PREDICTION_ERROR"

MIN_REQUIRED_TRAINING_SAMPLES = 15
RECOMMENDED_FULL_SAMPLES = 30


class AttendancePredictionService:
    """
    AttendancePredictionService provides genuine statistical Machine Learning 
    (StandardScaler + Ridge Regression) forecasting for employee next-month attendance.
    
    Advisory analytics only: strictly isolated from payroll calculations and leave approvals.
    """

    FEATURE_NAMES = [
        "prev_month_attendance_rate",
        "prev_3m_avg_attendance_rate",
        "prev_month_late_count",
        "prev_month_avg_working_hours",
        "prev_month_overtime_hours",
        "prev_month_unpaid_leave_days",
        "employee_tenure_months"
    ]

    FEATURE_LABELS = {
        "prev_month_attendance_rate": "Prior Month Attendance Rate (%)",
        "prev_3m_avg_attendance_rate": "Prior 3-Month Avg Attendance (%)",
        "prev_month_late_count": "Prior Month Late Arrivals (Days)",
        "prev_month_avg_working_hours": "Prior Month Avg Daily Hours",
        "prev_month_overtime_hours": "Prior Month Overtime Hours",
        "prev_month_unpaid_leave_days": "Prior Month Unpaid Leave Days",
        "employee_tenure_months": "Employee Tenure (Months)"
    }

    SCHEDULE_DISCLOSURE = (
        "Baseline calculation assumes a standard Monday–Friday work week (5 days/week); "
        "organizational holidays are not dynamically excluded."
    )

    @staticmethod
    def get_scheduled_workdays(year: int, month: int) -> int:
        """
        Calculates standard scheduled weekdays (Monday through Friday) in a calendar month.
        """
        days_in_month = calendar.monthrange(year, month)[1]
        workdays = sum(
            1 for d in range(1, days_in_month + 1)
            if date(year, month, d).weekday() < 5
        )
        return max(1, workdays)

    @staticmethod
    def extract_monthly_metrics(employee_id: int, month: int, year: int) -> dict:
        """
        Extracts historical monthly attendance summary metrics for a given employee and month.
        """
        records = Attendance.query.filter_by(
            employee_id=employee_id,
            is_active=True
        ).filter(
            db.extract("month", Attendance.date) == month,
            db.extract("year", Attendance.date) == year
        ).all()

        present_days = 0
        half_days = 0
        absent_days = 0
        leave_days = 0
        total_working_hours = Decimal("0.00")
        total_overtime_hours = Decimal("0.00")
        late_count = 0

        for r in records:
            if r.status == AttendanceStatus.PRESENT:
                present_days += 1
            elif r.status == AttendanceStatus.HALF_DAY:
                half_days += 1
            elif r.status == AttendanceStatus.ABSENT:
                absent_days += 1
            elif r.status == AttendanceStatus.ON_LEAVE:
                leave_days += 1

            if r.working_hours is not None:
                total_working_hours += Decimal(str(r.working_hours))
            if r.overtime_hours is not None:
                total_overtime_hours += Decimal(str(r.overtime_hours))
            if r.late_minutes > 0:
                late_count += 1

        scheduled_days = AttendancePredictionService.get_scheduled_workdays(year, month)
        effective_days = float(present_days) + 0.5 * float(half_days)
        raw_rate = (effective_days / float(scheduled_days)) * 100.0
        attendance_rate = min(100.0, max(0.0, round(raw_rate, 2)))

        active_working_days = present_days + half_days
        avg_working_hours = (
            float(total_working_hours) / active_working_days
            if active_working_days > 0 else 0.0
        )

        unpaid_leave_days = PayrollService.calculate_unpaid_leave_days(employee_id, month, year)

        return {
            "month": month,
            "year": year,
            "has_records": len(records) > 0,
            "present_days": present_days,
            "half_days": half_days,
            "absent_days": absent_days,
            "leave_days": leave_days,
            "total_records": len(records),
            "scheduled_days": scheduled_days,
            "attendance_rate": attendance_rate,
            "total_working_hours": float(total_working_hours),
            "avg_working_hours": round(avg_working_hours, 2),
            "total_overtime_hours": float(total_overtime_hours),
            "late_count": late_count,
            "unpaid_leave_days": unpaid_leave_days
        }

    @staticmethod
    def extract_features_for_target_month(employee_id: int, target_month: int, target_year: int) -> tuple[list[float] | None, float | None]:
        """
        Constructs feature vector X strictly using information before the target month (0% temporal data leakage).
        """
        prev_m = target_month - 1
        prev_y = target_year
        if prev_m == 0:
            prev_m = 12
            prev_y -= 1

        prev_metrics = AttendancePredictionService.extract_monthly_metrics(employee_id, prev_m, prev_y)
        if not prev_metrics["has_records"]:
            return None, None

        rates_3m = [prev_metrics["attendance_rate"]]
        cur_m, cur_y = prev_m, prev_y
        for _ in range(2):
            cur_m -= 1
            if cur_m == 0:
                cur_m = 12
                cur_y -= 1
            m_metrics = AttendancePredictionService.extract_monthly_metrics(employee_id, cur_m, cur_y)
            if m_metrics["has_records"]:
                rates_3m.append(m_metrics["attendance_rate"])

        prev_3m_avg = round(sum(rates_3m) / len(rates_3m), 2)

        emp = db.session.get(Employee, employee_id)
        if emp and emp.joining_date:
            ref_date = date(prev_y, prev_m, 1)
            tenure_months = max(
                0,
                (ref_date.year - emp.joining_date.year) * 12 + (ref_date.month - emp.joining_date.month)
            )
        else:
            tenure_months = 0

        feature_vector = [
            float(prev_metrics["attendance_rate"]),
            float(prev_3m_avg),
            float(prev_metrics["late_count"]),
            float(prev_metrics["avg_working_hours"]),
            float(prev_metrics["total_overtime_hours"]),
            float(prev_metrics["unpaid_leave_days"]),
            float(tenure_months)
        ]

        target_metrics = AttendancePredictionService.extract_monthly_metrics(employee_id, target_month, target_year)
        target_y = target_metrics["attendance_rate"] if target_metrics["has_records"] else None

        return feature_vector, target_y

    @staticmethod
    def build_training_dataset() -> tuple[np.ndarray, np.ndarray, list[dict]]:
        """
        Extracts all historical training observations chronologically without temporal leakage.
        """
        emp_months = db.session.query(
            Attendance.employee_id,
            db.extract("year", Attendance.date).label("year"),
            db.extract("month", Attendance.date).label("month")
        ).filter(
            Attendance.is_active == True
        ).group_by(
            Attendance.employee_id,
            db.extract("year", Attendance.date),
            db.extract("month", Attendance.date)
        ).order_by(
            db.extract("year", Attendance.date),
            db.extract("month", Attendance.date),
            Attendance.employee_id
        ).all()

        X_list = []
        y_list = []
        metadata_list = []

        for emp_id, y_val, m_val in emp_months:
            m_int = int(m_val)
            y_int = int(y_val)
            features, target = AttendancePredictionService.extract_features_for_target_month(emp_id, m_int, y_int)
            if features is not None and target is not None:
                X_list.append(features)
                y_list.append(target)
                metadata_list.append({
                    "employee_id": emp_id,
                    "target_month": m_int,
                    "target_year": y_int
                })

        if not X_list:
            return np.empty((0, len(AttendancePredictionService.FEATURE_NAMES))), np.empty((0,)), []

        return np.array(X_list, dtype=np.float64), np.array(y_list, dtype=np.float64), metadata_list

    @staticmethod
    def train_and_evaluate_model(X: np.ndarray, y: np.ndarray, metadata: list[dict]) -> dict:
        """
        Trains StandardScaler + Ridge Regression using Month-Grouped Temporal Validation.
        All employee observations for a given target calendar month stay in the same split.
        """
        n_samples = len(X)
        if n_samples < MIN_REQUIRED_TRAINING_SAMPLES:
            return {
                "trained": False,
                "reason": f"Insufficient historical dataset size ({n_samples}/{MIN_REQUIRED_TRAINING_SAMPLES} samples required).",
                "model": None,
                "scaler": None,
                "metrics": None
            }

        # Month-Grouped Temporal Validation Partitioning
        # 1. Collect unique target (year, month) tuples in chronological order
        unique_months = []
        for meta in metadata:
            ym = (meta["target_year"], meta["target_month"])
            if ym not in unique_months:
                unique_months.append(ym)

        if len(unique_months) >= 2:
            val_month_count = max(1, int(len(unique_months) * 0.2))
            train_months = set(unique_months[:-val_month_count])
            val_months = set(unique_months[-val_month_count:])

            train_indices = [
                i for i, meta in enumerate(metadata)
                if (meta["target_year"], meta["target_month"]) in train_months
            ]
            val_indices = [
                i for i, meta in enumerate(metadata)
                if (meta["target_year"], meta["target_month"]) in val_months
            ]
        else:
            # Fallback if only 1 calendar month exists
            split_idx = max(1, int(n_samples * 0.8))
            train_indices = list(range(split_idx))
            val_indices = list(range(split_idx, n_samples))

        X_train, y_train = X[train_indices], y[train_indices]
        X_val, y_val = X[val_indices], y[val_indices]

        # Fit training scaler and evaluation Ridge model
        eval_scaler = StandardScaler()
        X_train_scaled = eval_scaler.fit_transform(X_train)

        eval_ridge = Ridge(alpha=1.0)
        eval_ridge.fit(X_train_scaled, y_train)

        mae = None
        rmse = None
        r2 = None

        if len(y_val) > 0:
            X_val_scaled = eval_scaler.transform(X_val)
            y_pred = eval_ridge.predict(X_val_scaled)
            mae = float(mean_absolute_error(y_val, y_pred))
            rmse = float(root_mean_squared_error(y_val, y_pred))

            # R² guardrail: require >= 5 validation samples and non-zero target variance
            if len(y_val) >= 5 and float(np.var(y_val)) > 1e-4:
                r2_val = r2_score(y_val, y_pred)
                r2 = float(r2_val) if not np.isnan(r2_val) else None

        # Fit final production model on 100% of data AFTER evaluation is complete
        full_scaler = StandardScaler()
        X_full_scaled = full_scaler.fit_transform(X)
        full_model = Ridge(alpha=1.0)
        full_model.fit(X_full_scaled, y)

        return {
            "trained": True,
            "model": full_model,
            "scaler": full_scaler,
            "metrics": {
                "total_samples": n_samples,
                "validation_mae": round(mae, 2) if mae is not None else None,
                "validation_rmse": round(rmse, 2) if rmse is not None else None,
                "validation_r2": round(r2, 3) if r2 is not None else None,
                "coefficients": {
                    feat: round(float(coef), 4)
                    for feat, coef in zip(AttendancePredictionService.FEATURE_NAMES, full_model.coef_)
                },
                "intercept": round(float(full_model.intercept_), 2)
            }
        }

    @staticmethod
    def calculate_mathematical_contributions(features: list[float], scaler: StandardScaler, model: Ridge) -> list[dict]:
        """
        Derives mathematical feature contributions for Ridge + StandardScaler:
        z_i = (x_i - mean_i) / scale_i
        contribution_i = z_i * coef_i
        Does not use static heuristic rules.
        """
        contributions = []
        features_arr = np.array(features, dtype=np.float64)
        means = scaler.mean_
        scales = scaler.scale_
        coefs = model.coef_

        for i, feat_name in enumerate(AttendancePredictionService.FEATURE_NAMES):
            scale_val = scales[i] if scales[i] != 0 else 1.0
            z_score = (features_arr[i] - means[i]) / scale_val
            contrib = float(z_score * coefs[i])

            contributions.append({
                "feature": feat_name,
                "label": AttendancePredictionService.FEATURE_LABELS[feat_name],
                "raw_value": round(float(features_arr[i]), 2),
                "z_score": round(float(z_score), 2),
                "contribution": round(contrib, 2)
            })

        # Sort by magnitude of contribution
        contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
        return contributions

    @staticmethod
    def predict_next_month_attendance(employee_id: int, target_month: int | None = None, target_year: int | None = None) -> dict:
        """
        Predicts next month's attendance percentage for an employee using Ridge Regression.
        Bounded to [0.0, 100.0] with categorized risk bands and mathematical contributions.
        """
        emp = db.session.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return {
                "success": False,
                "state": STATE_PREDICTION_ERROR,
                "message": "Employee not found or inactive."
            }

        latest_rec = Attendance.query.filter_by(
            employee_id=employee_id,
            is_active=True
        ).order_by(Attendance.date.desc()).first()

        if not latest_rec:
            return {
                "success": False,
                "state": STATE_NO_DATA,
                "employee_id": employee_id,
                "employee_name": f"{emp.first_name} {emp.last_name}",
                "message": "No historical attendance logs found for this employee."
            }

        if target_month is None or target_year is None:
            latest_m = latest_rec.date.month
            latest_y = latest_rec.date.year
            next_m = latest_m + 1
            next_y = latest_y
            if next_m > 12:
                next_m = 1
                next_y += 1
        else:
            next_m = target_month
            next_y = target_year

        try:
            X, y, metadata = AttendancePredictionService.build_training_dataset()
        except Exception as e:
            logger.error("Error constructing training dataset: %s", str(e))
            return {
                "success": False,
                "state": STATE_PREDICTION_ERROR,
                "message": "Encountered an internal error building feature dataset."
            }

        training_result = AttendancePredictionService.train_and_evaluate_model(X, y, metadata)
        if not training_result["trained"]:
            return {
                "success": False,
                "state": STATE_INSUFFICIENT_DATA,
                "employee_id": employee_id,
                "employee_name": f"{emp.first_name} {emp.last_name}",
                "sample_count": len(X),
                "message": f"Insufficient historical attendance data for ML forecasting (minimum {MIN_REQUIRED_TRAINING_SAMPLES} monthly samples required; found {len(X)})."
            }

        features, _ = AttendancePredictionService.extract_features_for_target_month(employee_id, next_m, next_y)
        if features is None:
            return {
                "success": False,
                "state": STATE_INSUFFICIENT_DATA,
                "employee_id": employee_id,
                "employee_name": f"{emp.first_name} {emp.last_name}",
                "message": "Employee lacks attendance logs in the immediately preceding month required for prediction."
            }

        model = training_result["model"]
        scaler = training_result["scaler"]
        features_arr = np.array([features], dtype=np.float64)
        scaled_features = scaler.transform(features_arr)

        raw_pred = model.predict(scaled_features)[0]
        predicted_attendance = min(100.0, max(0.0, round(float(raw_pred), 1)))

        # Risk band determination (strict boundaries)
        if predicted_attendance >= 90.0:
            risk_band = "Low"
            risk_badge = "badge-pass"
        elif predicted_attendance >= 75.0:
            risk_band = "Moderate"
            risk_badge = "badge-warning"
        else:
            risk_band = "High"
            risk_badge = "badge-fail"

        # Mathematical Feature Contributions
        contributions = AttendancePredictionService.calculate_mathematical_contributions(features, scaler, model)

        total_samples = training_result["metrics"]["total_samples"]
        if total_samples < RECOMMENDED_FULL_SAMPLES:
            state = STATE_EXPERIMENTAL
            advisory_disclaimer = (
                f"Limited historical dataset ({total_samples} samples) — forecast is experimental "
                "and should be interpreted cautiously. For workforce planning only; human review required."
            )
        else:
            state = STATE_PREDICTION_AVAILABLE
            advisory_disclaimer = (
                "ML forecast based on historical attendance patterns. For workforce planning only; "
                "human review required."
            )

        target_month_label = f"{calendar.month_name[next_m]} {next_y}"

        return {
            "success": True,
            "state": state,
            "employee_id": employee_id,
            "employee_code": emp.employee_code,
            "employee_name": f"{emp.first_name} {emp.last_name}",
            "forecast_period": target_month_label,
            "forecast_month": next_m,
            "forecast_year": next_y,
            "predicted_attendance_rate": predicted_attendance,
            "risk_band": risk_band,
            "risk_badge": risk_badge,
            "model_contributions": contributions,
            "model_type": "Ridge Linear Regression",
            "validation_mae": training_result["metrics"]["validation_mae"],
            "validation_rmse": training_result["metrics"]["validation_rmse"],
            "validation_r2": training_result["metrics"]["validation_r2"],
            "training_samples": total_samples,
            "advisory_disclaimer": advisory_disclaimer,
            "schedule_disclosure": AttendancePredictionService.SCHEDULE_DISCLOSURE,
            "contribution_disclaimer": "Contributions indicate model feature influence relative to the baseline, not causal effects."
        }

    @staticmethod
    def get_organization_prediction_summary() -> list[dict]:
        """
        Generates predictions across all active employees for HR/Admin analytics dashboard.
        """
        employees = Employee.query.filter_by(is_active=True).all()
        results = []
        for emp in employees:
            pred = AttendancePredictionService.predict_next_month_attendance(emp.id)
            results.append(pred)
        return results
