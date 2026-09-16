from decimal import Decimal
from extensions import db
from models.department import Department
from models.employee import Employee, EmployeeStatus

class HRService:
    """
    HRService encapsulates all business logic for Departments and Employees.
    Ensures strict validation, duplicate checking, and soft delete rules.
    """

    @staticmethod
    def create_department(name, code, description=None):
        """Creates a new department with duplicate validation."""
        clean_name = name.strip()
        clean_code = code.strip()

        # Check duplicate name (case-insensitive)
        existing_name = Department.query.filter(
            db.func.lower(Department.name) == clean_name.lower()
        ).first()
        if existing_name:
            raise ValueError("A department with this name already exists.")

        # Check duplicate code (case-insensitive)
        existing_code = Department.query.filter(
            db.func.lower(Department.code) == clean_code.lower()
        ).first()
        if existing_code:
            raise ValueError("A department with this code already exists.")

        dept = Department(
            name=clean_name,
            code=clean_code,
            description=description.strip() if description else None
        )
        db.session.add(dept)
        db.session.commit()
        return dept

    @staticmethod
    def update_department(dept_id, data):
        """Updates department fields with duplicate validation."""
        dept = db.session.get(Department, dept_id)
        if not dept or not dept.is_active:
            raise ValueError("Department not found.")

        if "name" in data:
            clean_name = data["name"].strip()
            if clean_name.lower() != dept.name.lower():
                existing = Department.query.filter(
                    db.func.lower(Department.name) == clean_name.lower()
                ).first()
                if existing:
                    raise ValueError("A department with this name already exists.")
            dept.name = clean_name

        if "code" in data:
            clean_code = data["code"].strip()
            if clean_code.lower() != dept.code.lower():
                existing = Department.query.filter(
                    db.func.lower(Department.code) == clean_code.lower()
                ).first()
                if existing:
                    raise ValueError("A department with this code already exists.")
            dept.code = clean_code

        if "description" in data:
            dept.description = data["description"].strip() if data["description"] else None

        db.session.commit()
        return dept

    @staticmethod
    def soft_delete_department(dept_id):
        """Soft deletes a department if no active employees are assigned."""
        dept = db.session.get(Department, dept_id)
        if not dept or not dept.is_active:
            raise ValueError("Department not found.")

        # Block soft delete if active employees exist in department
        active_emp_count = Employee.query.filter(
            Employee.department_id == dept_id,
            Employee.is_active == True
        ).count()
        if active_emp_count > 0:
            raise ValueError("Cannot soft delete department because it has active employees assigned to it.")

        dept.is_active = False
        db.session.commit()

    @staticmethod
    def list_departments(search=None):
        """Lists active departments, optionally filtered by search query."""
        query = Department.query.filter(Department.is_active == True)
        if search:
            clean_search = f"%{search.strip()}%"
            query = query.filter(
                db.or_(
                    Department.name.ilike(clean_search),
                    Department.code.ilike(clean_search)
                )
            )
        return query.order_by(Department.name).all()

    @staticmethod
    def create_employee(data):
        """Creates a new employee with database integrity validations."""
        email = data["email"].strip().lower()
        employee_code = data["employee_code"].strip().upper()
        status = data.get("status", EmployeeStatus.ACTIVE).strip()
        dept_id = int(data["department_id"])

        # Validate duplicate email
        existing_email = Employee.query.filter(
            db.func.lower(Employee.email) == email
        ).first()
        if existing_email:
            raise ValueError("An employee with this email address already exists.")

        # Validate duplicate employee_code
        existing_code = Employee.query.filter(
            db.func.lower(Employee.employee_code) == employee_code.lower()
        ).first()
        if existing_code:
            raise ValueError("An employee with this employee code already exists.")

        # Validate department exists and is active
        dept = db.session.get(Department, dept_id)
        if not dept or not dept.is_active:
            raise ValueError("Selected department does not exist or is inactive.")

        # Validate status choices
        if status not in EmployeeStatus.CHOICES:
            raise ValueError(f"Invalid employee status '{status}'. Must be one of {EmployeeStatus.CHOICES}")

        salary = Decimal(str(data["basic_salary"]))

        new_emp = Employee(
            employee_code=employee_code,
            first_name=data["first_name"].strip(),
            last_name=data["last_name"].strip(),
            email=email,
            phone=data.get("phone").strip() if data.get("phone") else None,
            gender=data.get("gender").strip() if data.get("gender") else None,
            date_of_birth=data.get("date_of_birth"),
            address=data.get("address").strip() if data.get("address") else None,
            joining_date=data["joining_date"],
            employment_type=data["employment_type"],
            basic_salary=salary,
            bank_account_number=data.get("bank_account_number").strip() if data.get("bank_account_number") else None,
            ifsc_code=data.get("ifsc_code").strip().upper() if data.get("ifsc_code") else None,
            pan_number=data.get("pan_number").strip().upper() if data.get("pan_number") else None,
            aadhaar_number=data.get("aadhaar_number").strip() if data.get("aadhaar_number") else None,
            emergency_contact=data.get("emergency_contact").strip() if data.get("emergency_contact") else None,
            status=status,
            department_id=dept_id
        )

        db.session.add(new_emp)
        db.session.commit()
        return new_emp

    @staticmethod
    def update_employee(emp_id, data):
        """Updates employee fields with database integrity validations."""
        emp = db.session.get(Employee, emp_id)
        if not emp or not emp.is_active:
            raise ValueError("Employee not found.")

        if "email" in data:
            email = data["email"].strip().lower()
            if email != emp.email.lower():
                existing = Employee.query.filter(
                    db.func.lower(Employee.email) == email
                ).first()
                if existing:
                    raise ValueError("An employee with this email address already exists.")
            emp.email = email

        if "employee_code" in data:
            employee_code = data["employee_code"].strip().upper()
            if employee_code != emp.employee_code:
                existing = Employee.query.filter(
                    db.func.lower(Employee.employee_code) == employee_code.lower()
                ).first()
                if existing:
                    raise ValueError("An employee with this employee code already exists.")
            emp.employee_code = employee_code

        if "department_id" in data:
            dept_id = int(data["department_id"])
            if dept_id != emp.department_id:
                dept = db.session.get(Department, dept_id)
                if not dept or not dept.is_active:
                    raise ValueError("Selected department does not exist or is inactive.")
            emp.department_id = dept_id

        if "status" in data:
            status = data["status"].strip()
            if status not in EmployeeStatus.CHOICES:
                raise ValueError(f"Invalid employee status '{status}'.")
            emp.status = status

        # Update remaining personal details
        if "first_name" in data:
            emp.first_name = data["first_name"].strip()
        if "last_name" in data:
            emp.last_name = data["last_name"].strip()
        if "phone" in data:
            emp.phone = data["phone"].strip() if data["phone"] else None
        if "gender" in data:
            emp.gender = data["gender"].strip() if data["gender"] else None
        if "date_of_birth" in data:
            emp.date_of_birth = data["date_of_birth"]
        if "address" in data:
            emp.address = data["address"].strip() if data["address"] else None
        if "joining_date" in data:
            emp.joining_date = data["joining_date"]
        if "employment_type" in data:
            emp.employment_type = data["employment_type"]
        if "basic_salary" in data:
            emp.basic_salary = Decimal(str(data["basic_salary"]))
        if "bank_account_number" in data:
            emp.bank_account_number = data["bank_account_number"].strip() if data["bank_account_number"] else None
        if "ifsc_code" in data:
            emp.ifsc_code = data["ifsc_code"].strip().upper() if data["ifsc_code"] else None
        if "pan_number" in data:
            emp.pan_number = data["pan_number"].strip().upper() if data["pan_number"] else None
        if "aadhaar_number" in data:
            emp.aadhaar_number = data["aadhaar_number"].strip() if data["aadhaar_number"] else None
        if "emergency_contact" in data:
            emp.emergency_contact = data["emergency_contact"].strip() if data["emergency_contact"] else None

        db.session.commit()
        return emp

    @staticmethod
    def soft_delete_employee(emp_id):
        """Soft deletes an employee."""
        emp = db.session.get(Employee, emp_id)
        if not emp or not emp.is_active:
            raise ValueError("Employee not found.")

        emp.is_active = False
        db.session.commit()

    @staticmethod
    def list_employees(search=None, department_id=None, page=1):
        """Lists active employees, paginated and optionally filtered."""
        query = Employee.query.filter(Employee.is_active == True)

        if department_id:
            query = query.filter(Employee.department_id == int(department_id))

        if search:
            clean_search = f"%{search.strip()}%"
            query = query.filter(
                db.or_(
                    Employee.first_name.ilike(clean_search),
                    Employee.last_name.ilike(clean_search),
                    Employee.email.ilike(clean_search),
                    Employee.employee_code.ilike(clean_search)
                )
            )

        # Order by joining_date descending for list view consistency
        query = query.order_by(Employee.last_name, Employee.first_name)
        return query.paginate(page=page, per_page=10, error_out=False)
