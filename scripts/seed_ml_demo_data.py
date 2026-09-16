"""
Developer CLI Utility: Seed ML Demo Attendance Data
==================================================
WARNING: This script generates SYNTHETIC DEMO DATA for testing and academic demonstration.
Do NOT run this script in production environments as synthetic records will affect payroll,
overtime, and historical attendance metrics.

Usage:
  python scripts/seed_ml_demo_data.py [--months 4] [--seed 42]
"""

import sys
import os
import calendar
import random
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models.attendance import Attendance, AttendanceStatus
from models.employee import Employee


def seed_demo_attendance_data(num_months: int = 4, random_seed: int = 42) -> dict:
    """
    Seeds synthetic historical attendance records for active employees for developer demonstration.
    """
    random.seed(random_seed)
    employees = Employee.query.filter_by(is_active=True).all()
    if not employees:
        print("[!] No active employees found in the database.")
        return {"success": False, "created_records": 0}

    today = date.today()
    created_count = 0

    for offset in range(num_months, 0, -1):
        m = today.month - offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1

        days_in_m = calendar.monthrange(y, m)[1]

        for emp in employees:
            base_prob_present = 0.88 + (emp.id % 3) * 0.04

            for day_num in range(1, days_in_m + 1):
                rec_date = date(y, m, day_num)
                if rec_date.weekday() >= 5:
                    continue

                existing = Attendance.query.filter_by(employee_id=emp.id, date=rec_date).first()
                if existing:
                    continue

                rand_val = random.random()
                if rand_val < base_prob_present:
                    status = AttendanceStatus.PRESENT
                    late_mins = random.choice([0, 0, 0, 0, 10, 20, 35]) if random.random() < 0.25 else 0
                    overtime = Decimal(str(random.choice([0.0, 0.0, 0.5, 1.5, 2.0]))) if random.random() < 0.3 else Decimal("0.00")
                    work_hours = Decimal("8.00") + overtime - Decimal(str(late_mins / 60.0))
                    work_hours = max(Decimal("4.00"), work_hours.quantize(Decimal("0.01")))

                    check_in_time = datetime(y, m, day_num, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=late_mins)
                    check_out_time = check_in_time + timedelta(hours=float(work_hours))
                elif rand_val < base_prob_present + 0.06:
                    status = AttendanceStatus.HALF_DAY
                    late_mins = 0
                    overtime = Decimal("0.00")
                    work_hours = Decimal("4.00")
                    check_in_time = datetime(y, m, day_num, 9, 0, tzinfo=timezone.utc)
                    check_out_time = check_in_time + timedelta(hours=4)
                else:
                    status = AttendanceStatus.ABSENT
                    late_mins = 0
                    overtime = Decimal("0.00")
                    work_hours = Decimal("0.00")
                    check_in_time = None
                    check_out_time = None

                att = Attendance(
                    employee_id=emp.id,
                    date=rec_date,
                    check_in=check_in_time,
                    check_out=check_out_time,
                    working_hours=work_hours,
                    overtime_hours=overtime,
                    late_minutes=late_mins,
                    early_leave_minutes=0,
                    status=status
                )
                db.session.add(att)
                created_count += 1

    try:
        db.session.commit()
        print(f"[+] Successfully seeded {created_count} synthetic demo attendance records.")
        return {"success": True, "created_records": created_count}
    except Exception as e:
        db.session.rollback()
        print(f"[-] Failed to seed demo attendance: {str(e)}")
        return {"success": False, "created_records": 0}


if __name__ == "__main__":
    print("=========================================================================")
    print("  DEVELOPER UTILITY: SEED SYNTHETIC ATTENDANCE DATA FOR ML DEMONSTRATION")
    print("=========================================================================")
    print("  WARNING: Synthetic data MUST NOT be interpreted as real model accuracy")
    print("           or evidence of production system performance.")
    print("=========================================================================")
    
    app = create_app()
    with app.app_context():
        seed_demo_attendance_data(num_months=4, random_seed=42)
