import os
import json
import logging
import requests
from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models.employee import Employee
from models.payroll import Payroll
from models.ai_conversation import AIConversation
from blueprints.payroll.services import PayrollService

logger = logging.getLogger(__name__)

class AIService:
    """
    AIService manages payroll analytics explanation and queries using Gemini AI.
    """

    @staticmethod
    def generate_payroll_analysis(employee_id: int, month: int, year: int, user_id: int) -> dict:
        """
        Retrieves payroll, attendance, anomaly, and government compliance data,
        constructs a prompt for Gemini, invokes the Gemini API, logs the conversation,
        and returns the upgraded compliance-aware payroll analysis.
        """
        # 1. Fetch payroll record
        payroll = Payroll.query.filter_by(
            employee_id=employee_id,
            month=month,
            year=year,
            is_active=True
        ).first()

        if not payroll:
            return {
                "success": False,
                "message": "Payroll record not found."
            }

        # Fetch employee details
        emp = db.session.get(Employee, employee_id)
        if not emp:
            return {
                "success": False,
                "message": "Employee not found."
            }

        # 2. Fetch anomaly detection result
        anomaly_res = PayrollService.detect_payroll_anomaly(employee_id, month, year)
        anomaly_reasons = anomaly_res.get("reasons", [])
        severity_level = anomaly_res.get("severity") or "None"

        # 3. Fetch government compliance validation result
        compliance_res = PayrollService.validate_payroll_against_government_rules(payroll.id)
        compliance_status = compliance_res.get("overall_status") or "PASS"
        gov_violations = compliance_res.get("violations", [])

        # Fetch attendance metrics
        att_summary = PayrollService.calculate_monthly_attendance_summary(employee_id, month, year)
        overtime_hours = att_summary.get("overtime_hours", Decimal("0.00"))
        unpaid_leave_days = PayrollService.calculate_unpaid_leave_days(employee_id, month, year)

        employee_name = f"{emp.first_name} {emp.last_name}"

        # 4. Build structured prompt (upgraded with government compliance)
        prompt = (
            f"You are a professional HR and Payroll Analytics Assistant.\n"
            f"Analyze the following payroll, attendance, and compliance data for the employee:\n"
            f"Employee Name: {employee_name}\n"
            f"Employee ID: {emp.employee_code}\n"
            f"Gross Salary: {payroll.gross_salary:,.2f}\n"
            f"Net Salary: {payroll.net_salary:,.2f}\n"
            f"Overtime Hours: {overtime_hours}\n"
            f"Unpaid Leave Days: {unpaid_leave_days}\n"
            f"Anomaly Reasons: {', '.join(anomaly_reasons) if anomaly_reasons else 'None'}\n"
            f"Anomaly Severity Level: {severity_level}\n"
            f"Overall Government Compliance Status: {compliance_status}\n"
            f"Government Rule Violations: {', '.join(gov_violations) if gov_violations else 'None'}\n\n"
            f"Task:\n"
            f"- Summarize payroll health.\n"
            f"- Explain anomaly triggers (if any).\n"
            f"- Explain compliance risks (if any).\n"
            f"- Provide HR recommendations to address these items.\n"
            f"- Assign a risk rating (Low/Medium/High).\n\n"
            f"You must return a JSON object with the following schema:\n"
            f"{{\n"
            f"   \"summary\": \"A detailed analysis explaining why the anomalies and compliance violations occurred.\",\n"
            f"   \"risk_rating\": \"Low/Medium/High\",\n"
            f"   \"compliance_status\": \"PASS/FAIL/WARNING\",\n"
            f"   \"recommendation\": \"Actionable steps for HR or payroll managers to take.\",\n"
            f"   \"anomaly_reasons\": [\"reason1\", \"reason2\"],\n"
            f"   \"government_violations\": [\"violation1\", \"violation2\"]\n"
            f"}}\n"
            f"Do not include any formatting like ```json or markdown blocks. Just return the raw JSON object."
        )

        api_key = os.environ.get("GEMINI_API_KEY")
        
        summary_text = ""
        risk_rating = severity_level
        rec_text = ""
        is_fallback = False

        if not api_key:
            logger.warning("GEMINI_API_KEY environment variable not configured. Using fallback explanation.")
            is_fallback = True
        else:
            # Call Gemini API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json"
                }
            }

            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10.0)
                if response.status_code == 200:
                    resp_json = response.json()
                    text_content = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_content.strip())
                    
                    summary_text = parsed.get("summary", "")
                    risk_rating = parsed.get("risk_rating", severity_level)
                    compliance_status = parsed.get("compliance_status", compliance_status)
                    rec_text = parsed.get("recommendation", "")
                    # Fetch lists if returned by model, otherwise default to resolved lists
                    anomaly_reasons = parsed.get("anomaly_reasons", anomaly_reasons)
                    gov_violations = parsed.get("government_violations", gov_violations)
                else:
                    logger.error("Gemini API call failed with status %d: %s", response.status_code, response.text)
                    is_fallback = True
            except Exception as e:
                logger.error("Error communicating with Gemini API: %s", str(e))
                is_fallback = True

        if is_fallback:
            # Build structured fallback explanations based on resolved stats
            summary_text = (
                f"Gemini AI analysis is temporarily unavailable. Deterministic rule-based analysis detected "
                f"anomaly reasons: {', '.join(anomaly_reasons) if anomaly_reasons else 'None'} and compliance "
                f"violations: {', '.join(gov_violations) if gov_violations else 'None'}."
            )
            rec_text = (
                "Please manually review the employee's monthly attendance logs, overtime sheets, and "
                "leave requests to verify the calculations."
            )
            # Ensure risk rating maps to severity_level fallback
            risk_rating = severity_level

        # Store Full AI Report in AIConversation table
        result_payload = {
            "summary": summary_text,
            "risk_rating": risk_rating,
            "compliance_status": compliance_status,
            "recommendation": rec_text,
            "anomaly_reasons": anomaly_reasons,
            "government_violations": gov_violations
        }

        convo = AIConversation(
            user_id=user_id,
            employee_id=employee_id,
            month=month,
            year=year,
            prompt=prompt,
            response=json.dumps(result_payload),
            timestamp=datetime.now(timezone.utc)
        )

        try:
            db.session.add(convo)
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            logger.error("Failed to commit AIConversation record: %s", str(db_err))

        return result_payload

    @staticmethod
    def generate_executive_summary(month: int, year: int, user_id: int) -> dict:
        """
        Gathers system-wide aggregated metrics, invokes Gemini API to construct
        an executive organization-level report summary, and caches the result.
        """
        # Import AnalyticsService dynamically to prevent circular imports
        from blueprints.analytics.services import AnalyticsService

        # Gather trend metrics
        payroll_trend = AnalyticsService.get_payroll_trend(last_n_months=6)
        attendance_trend = AnalyticsService.get_attendance_trend(last_n_months=6)
        leave_stats = AnalyticsService.get_leave_statistics(year=year)
        compliance_summary = AnalyticsService.get_compliance_risk_summary(month=month, year=year)

        # Build prompt
        prompt = (
            f"You are a senior payroll director and compliance advisor.\n"
            f"Analyze the organization's payroll, attendance, and compliance aggregates for {month:02d}-{year}:\n\n"
            f"Payroll Trend:\n{json.dumps(payroll_trend, indent=2)}\n\n"
            f"Attendance Trend:\n{json.dumps(attendance_trend, indent=2)}\n\n"
            f"Leave Statistics:\n{json.dumps(leave_stats, indent=2)}\n\n"
            f"Compliance Summary for the Month:\n{json.dumps(compliance_summary, indent=2)}\n\n"
            f"Provide an Executive Summary explaining:\n"
            f"1. Payroll growth trend.\n"
            f"2. Attendance health.\n"
            f"3. Compliance risk overview.\n"
            f"4. Specific HR recommendations to optimize operations and compliance.\n\n"
            f"You must return a JSON object with the following schema:\n"
            f"{{\n"
            f"   \"summary\": \"A detailed executive report summarizing trends, compliance risks, and workforce health.\",\n"
            f"   \"recommendation\": \"Actionable, prioritized steps for HR management.\"\n"
            f"}}\n"
            f"Do not include any formatting like ```json or markdown blocks. Just return the raw JSON object."
        )

        api_key = os.environ.get("GEMINI_API_KEY")
        summary_text = ""
        rec_text = ""
        is_fallback = False

        if not api_key:
            logger.warning("GEMINI_API_KEY environment variable not configured. Using fallback executive summary.")
            is_fallback = True
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json"
                }
            }

            try:
                response = requests.post(url, headers=headers, json=payload, timeout=12.0)
                if response.status_code == 200:
                    resp_json = response.json()
                    text_content = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_content.strip())
                    summary_text = parsed.get("summary", "")
                    rec_text = parsed.get("recommendation", "")
                else:
                    logger.error("Gemini Executive API call failed with status %d: %s", response.status_code, response.text)
                    is_fallback = True
            except Exception as e:
                logger.error("Error communicating with Gemini Executive API: %s", str(e))
                is_fallback = True

        if is_fallback:
            summary_text = (
                f"Deterministic rule-based executive summary: Monthly payroll aggregates show total costs "
                f"of {sum(payroll_trend.get('total_cost', [])):,.2f} across the observed periods. Compliance validation "
                f"logged {compliance_summary.get('fail', 0)} FAILs and {compliance_summary.get('warning', 0)} WARNINGs."
            )
            rec_text = (
                "Please manually review the dashboard charts, compliance validation logs, and pending "
                "leave request queues to optimize workforce planning."
            )

        # Log conversation (dummy employee_id=0 or -1 representing organization-level executive query)
        convo = AIConversation(
            user_id=user_id,
            employee_id=1,  # fallback to general placeholder ID
            month=month,
            year=year,
            prompt=prompt,
            response=json.dumps({"summary": summary_text, "recommendation": rec_text}),
            timestamp=datetime.now(timezone.utc)
        )

        try:
            db.session.add(convo)
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            logger.error("Failed to commit AI Executive Conversation record: %s", str(db_err))

        return {
            "summary": summary_text,
            "recommendation": rec_text
        }

