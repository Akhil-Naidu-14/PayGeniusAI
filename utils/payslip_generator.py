import calendar
from datetime import datetime, timezone
from io import BytesIO
from decimal import Decimal
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_payslip_pdf(payroll, employee, department) -> BytesIO:
    """
    Generates a professional PDF payslip for a given payroll record.
    Returns a BytesIO stream containing the PDF binary data.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    story = []
    styles = getSampleStyleSheet()

    # Color Palette
    primary_color = colors.HexColor("#1A365D")  # Dark Slate Blue
    secondary_color = colors.HexColor("#4A5568") # Slate Gray
    accent_color = colors.HexColor("#2B6CB0")    # Classic Blue
    bg_light = colors.HexColor("#F7FAFC")        # Soft White/Gray
    border_color = colors.HexColor("#E2E8F0")    # Light Gray

    # Custom Typography Styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=primary_color,
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=secondary_color,
        spaceAfter=15
    )
    section_title_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=primary_color,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=secondary_color
    )
    body_bold_style = ParagraphStyle(
        "BodyTextBoldCustom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=primary_color
    )
    net_salary_style = ParagraphStyle(
        "NetSalary",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        textColor=colors.HexColor("#2F855A") # Green for positive net salary
    )

    # 1. Header Section
    story.append(Paragraph("PayGenius AI", title_style))
    month_name = calendar.month_name[payroll.month]
    story.append(Paragraph(f"PAYSLIP FOR {month_name.upper()} {payroll.year}", subtitle_style))
    story.append(Spacer(1, 10))

    # 2. Employee Details Block
    dept_name = department.name if department else "N/A"
    emp_details = [
        [
            Paragraph("Employee Name:", body_bold_style),
            Paragraph(f"{employee.first_name} {employee.last_name}", body_style),
            Paragraph("Employee ID:", body_bold_style),
            Paragraph(employee.employee_code, body_style)
        ],
        [
            Paragraph("Department:", body_bold_style),
            Paragraph(dept_name, body_style),
            Paragraph("Employment Type:", body_bold_style),
            Paragraph(employee.employment_type, body_style)
        ],
        [
            Paragraph("Pay Period:", body_bold_style),
            Paragraph(f"{month_name} {payroll.year}", body_style),
            Paragraph("Payment Status:", body_bold_style),
            Paragraph(payroll.status, body_style)
        ]
    ]

    details_table = Table(emp_details, colWidths=[100, 160, 100, 160])
    details_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_light),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, border_color),
        ("BOX", (0, 0), (-1, -1), 1, primary_color),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 20))

    # 3. Earnings & Deductions Breakdown
    story.append(Paragraph("Salary Structure Breakdown", section_title_style))

    # Calculate unpaid leave deduction
    unpaid_deduction = payroll.total_deductions - (
        payroll.provident_fund
        + payroll.professional_tax
        + payroll.income_tax
        + payroll.loan_deduction
        + payroll.insurance_deduction
        + payroll.medical_allowance
        + payroll.travel_allowance
    )
    if unpaid_deduction < Decimal("0.00"):
        unpaid_deduction = Decimal("0.00")

    breakdown_data = [
        # Headers
        [
            Paragraph("Earnings", body_bold_style),
            Paragraph("Amount", body_bold_style),
            Paragraph("Deductions", body_bold_style),
            Paragraph("Amount", body_bold_style)
        ],
        # Rows
        [
            Paragraph("Basic Salary", body_style),
            Paragraph(f"{payroll.basic_salary:,.2f}", body_style),
            Paragraph("Provident Fund", body_style),
            Paragraph(f"{payroll.provident_fund:,.2f}", body_style)
        ],
        [
            Paragraph("Overtime Pay", body_style),
            Paragraph(f"{payroll.overtime_pay:,.2f}", body_style),
            Paragraph("Professional Tax", body_style),
            Paragraph(f"{payroll.professional_tax:,.2f}", body_style)
        ],
        [
            Paragraph("Bonus", body_style),
            Paragraph(f"{payroll.bonus:,.2f}", body_style),
            Paragraph("Income Tax (TDS)", body_style),
            Paragraph(f"{payroll.income_tax:,.2f}", body_style)
        ],
        [
            Paragraph("Incentives", body_style),
            Paragraph(f"{payroll.incentive:,.2f}", body_style),
            Paragraph("Loan/Advance Deductions", body_style),
            Paragraph(f"{payroll.loan_deduction:,.2f}", body_style)
        ],
        [
            Paragraph("", body_style),
            Paragraph("", body_style),
            Paragraph("Insurance Premium", body_style),
            Paragraph(f"{payroll.insurance_deduction:,.2f}", body_style)
        ],
        [
            Paragraph("", body_style),
            Paragraph("", body_style),
            Paragraph("Unpaid Leave Deduction", body_style),
            Paragraph(f"{unpaid_deduction:,.2f}", body_style)
        ],
        [
            Paragraph("", body_style),
            Paragraph("", body_style),
            Paragraph("Medical Allowance (Deducted)", body_style),
            Paragraph(f"{payroll.medical_allowance:,.2f}", body_style)
        ],
        [
            Paragraph("", body_style),
            Paragraph("", body_style),
            Paragraph("Travel Allowance (Deducted)", body_style),
            Paragraph(f"{payroll.travel_allowance:,.2f}", body_style)
        ],
        # Totals
        [
            Paragraph("Gross Salary", body_bold_style),
            Paragraph(f"{payroll.gross_salary:,.2f}", body_bold_style),
            Paragraph("Total Deductions", body_bold_style),
            Paragraph(f"{payroll.total_deductions:,.2f}", body_bold_style)
        ]
    ]

    breakdown_table = Table(breakdown_data, colWidths=[160, 100, 160, 100])
    breakdown_table.setStyle(TableStyle([
        # Headers Row
        ("BACKGROUND", (0, 0), (-1, 0), primary_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
        # Zebra coloring for data rows
        ("BACKGROUND", (0, 1), (-1, -2), bg_light),
        # Totals Row Styling
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
        ("LINEABOVE", (0, -1), (-1, -1), 1, primary_color),
        # Grid lines
        ("GRID", (0, 0), (-1, -1), 0.5, border_color),
    ]))
    # Quick text color adjust for headers
    for i in [0, 1, 2, 3]:
        breakdown_data[0][i].style.textColor = colors.white

    story.append(breakdown_table)
    story.append(Spacer(1, 25))

    # 4. Summary & Signature Block
    summary_data = [
        [
            Paragraph("NET TAKE-HOME SALARY:", body_bold_style),
            Paragraph(f"{payroll.net_salary:,.2f}", net_salary_style)
        ],
        [
            Paragraph("Payslip Generated On:", body_style),
            Paragraph(datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M UTC"), body_style)
        ]
    ]
    summary_table = Table(summary_data, colWidths=[180, 340])
    summary_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 1, primary_color),
    ]))
    story.append(summary_table)

    story.append(Spacer(1, 40))
    story.append(Paragraph("This is a computer-generated document and does not require a physical signature.", body_style))

    # Build document
    doc.build(story)
    buffer.seek(0)
    return buffer
