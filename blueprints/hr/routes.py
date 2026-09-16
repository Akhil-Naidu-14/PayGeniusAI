from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required
from blueprints.auth.decorators import roles_required
from models.role import RoleType
from blueprints.hr import hr_bp
from blueprints.hr.forms import DepartmentForm, EmployeeForm
from blueprints.hr.services import HRService

@hr_bp.route("/departments", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def list_departments():
    """Lists all active departments with search capabilities."""
    search_query = request.args.get("q", "")
    departments = HRService.list_departments(search=search_query)
    return render_template(
        "hr/department_list.html",
        departments=departments,
        search_query=search_query
    )


@hr_bp.route("/departments/create", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def create_department():
    """Handles new department creation requests."""
    form = DepartmentForm()
    if form.validate_on_submit():
        try:
            HRService.create_department(
                name=form.name.data,
                code=form.code.data,
                description=form.description.data
            )
            flash("Department successfully created.", "success")
            return redirect(url_for("hr.list_departments"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("hr/department_form.html", form=form, title="Create Department")


@hr_bp.route("/departments/edit/<int:id>", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def edit_department(id):
    """Handles updating department information."""
    try:
        departments = HRService.list_departments()
        dept = next((d for d in departments if d.id == id), None)
        if not dept:
            # Fallback direct get if not found in active list
            from extensions import db
            from models.department import Department
            dept = db.session.get(Department, id)
            if not dept or not dept.is_active:
                flash("Department not found.", "danger")
                return redirect(url_for("hr.list_departments"))

        form = DepartmentForm(obj=dept)
        if form.validate_on_submit():
            HRService.update_department(
                dept_id=id,
                data={
                    "name": form.name.data,
                    "code": form.code.data,
                    "description": form.description.data
                }
            )
            flash("Department successfully updated.", "success")
            return redirect(url_for("hr.list_departments"))
        return render_template("hr/department_form.html", form=form, title="Edit Department")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("hr.list_departments"))


@hr_bp.route("/departments/delete/<int:id>", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def delete_department(id):
    """Handles department soft deletion."""
    try:
        HRService.soft_delete_department(id)
        flash("Department successfully deleted.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("hr.list_departments"))


@hr_bp.route("/employees", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def list_employees():
    """Lists all active employees with search and department filtering."""
    search_query = request.args.get("q", "")
    department_id = request.args.get("department_id", "")
    page = request.args.get("page", 1, type=int)

    # Fetch filters and pagination
    dept_filter = int(department_id) if department_id.isdigit() else None
    pagination = HRService.list_employees(
        search=search_query,
        department_id=dept_filter,
        page=page
    )
    departments = HRService.list_departments()

    return render_template(
        "hr/employee_list.html",
        pagination=pagination,
        departments=departments,
        selected_dept=department_id,
        search_query=search_query
    )


@hr_bp.route("/employees/create", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def create_employee():
    """Handles registration of new system employees."""
    form = EmployeeForm()
    # Dynamically bind active departments
    form.department_id.choices = [
        (d.id, f"{d.name} ({d.code})") for d in HRService.list_departments()
    ]

    if form.validate_on_submit():
        try:
            HRService.create_employee(form.data)
            flash("Employee successfully registered.", "success")
            return redirect(url_for("hr.list_employees"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("hr/employee_form.html", form=form, title="Register Employee")


@hr_bp.route("/employees/edit/<int:id>", methods=["GET", "POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def edit_employee(id):
    """Handles employee details updates."""
    from extensions import db
    from models.employee import Employee
    emp = db.session.get(Employee, id)
    if not emp or not emp.is_active:
        flash("Employee not found.", "danger")
        return redirect(url_for("hr.list_employees"))

    form = EmployeeForm(obj=emp)
    form.department_id.choices = [
        (d.id, f"{d.name} ({d.code})") for d in HRService.list_departments()
    ]

    if form.validate_on_submit():
        try:
            HRService.update_employee(emp_id=id, data=form.data)
            flash("Employee successfully updated.", "success")
            return redirect(url_for("hr.list_employees"))
        except ValueError as e:
            flash(str(e), "danger")

    return render_template("hr/employee_form.html", form=form, title="Edit Employee")


@hr_bp.route("/employees/detail/<int:id>", methods=["GET"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def employee_detail(id):
    """Displays full details of a specific employee."""
    from extensions import db
    from models.employee import Employee
    emp = db.session.get(Employee, id)
    if not emp or not emp.is_active:
        flash("Employee not found.", "danger")
        return redirect(url_for("hr.list_employees"))
    return render_template("hr/employee_detail.html", employee=emp)


@hr_bp.route("/employees/delete/<int:id>", methods=["POST"])
@login_required
@roles_required(RoleType.ADMIN, RoleType.HR)
def delete_employee(id):
    """Handles soft deactivation of employees."""
    try:
        HRService.soft_delete_employee(id)
        flash("Employee successfully deleted.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("hr.list_employees"))
