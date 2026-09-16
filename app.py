import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template

from extensions import db, migrate, login_manager, csrf
from config import config_by_name

def create_app(config_name=None):
    """
    Application Factory Pattern.
    Initializes configuration, extensions, logging, blueprints, and middleware.
    """
    if not config_name:
        # Default to environment config or 'development'
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # Initialize extensions with current application context
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Login Manager configurations
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    if app.config.get("TESTING"):
        login_manager.session_protection = None


    # User Loader configuration
    from models.user import User
    @login_manager.user_loader
    def load_user(user_id):
        u = db.session.get(User, int(user_id))
        print(f"DEBUG USER_LOADER: user_id={user_id}, user={u}")
        return u



    # Secure HTTP Headers Middleware
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
        return response




    # Register Blueprints
    from blueprints.main import main_bp
    from blueprints.auth import auth_bp
    from blueprints.hr import hr_bp
    from blueprints.attendance import attendance_bp
    from blueprints.leave import leave_bp
    from blueprints.payroll import payroll_bp
    from blueprints.attendance_upload import attendance_upload_bp
    from blueprints.ai import ai_bp
    from blueprints.analytics import analytics_bp
    from blueprints.leave_encashment import leave_encashment_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(hr_bp, url_prefix="/hr")
    app.register_blueprint(attendance_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(payroll_bp, url_prefix="/payroll")
    app.register_blueprint(attendance_upload_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(leave_encashment_bp)



    @app.context_processor
    def inject_roles():
        from models.role import RoleType
        return dict(RoleType=RoleType)

    # Register Global Error Handlers
    register_error_handlers(app)

    # Register CLI Commands
    register_cli_commands(app)
    _register_seed_demo_data(app)

    # Setup environment-based logging
    configure_logging(app)

    return app


def register_cli_commands(app):
    """Registers custom flask CLI commands."""
    import click
    from flask.cli import with_appcontext
    from extensions import db
    from models.role import Role, RoleType
    from models.user import User
    import secrets
    import string
    from werkzeug.security import generate_password_hash

    @app.cli.command("seed-auth")
    @with_appcontext
    def seed_auth():
        """Idempotent seed command for RBAC roles and initial Admin user."""
        click.echo("Seeding roles and initial administrator...")

        admin_username = os.environ.get("ADMIN_USERNAME", "admin").strip()
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@paygenius.ai").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD")

        generated_password = None

        if not admin_password:
            # Check environment using env variables since CLI runner overrides app.debug
            is_dev = (
                os.environ.get("FLASK_ENV") == "development" or 
                os.environ.get("FLASK_DEBUG") == "1" or 
                app.config.get("TESTING")
            )
            is_prod = not is_dev

            if is_prod:
                raise click.UsageError(
                    "CRITICAL: ADMIN_PASSWORD environment variable must be set in production mode!"
                )
            else:
                # Generate a secure random password for local development
                alphabet = string.ascii_letters + string.digits
                generated_password = "".join(secrets.choice(alphabet) for _ in range(16))
                admin_password = generated_password


        try:
            # Execute database updates under nested transaction scope
            with db.session.begin(nested=True):
                # 1. Seed default privilege roles
                roles_to_create = [
                    (RoleType.ADMIN, "System Administrator"),
                    (RoleType.HR, "HR Manager"),
                    (RoleType.EMPLOYEE, "Employee")
                ]

                for role_name, description in roles_to_create:
                    role = Role.query.filter_by(name=role_name).first()
                    if not role:
                        role = Role(name=role_name, description=description)
                        db.session.add(role)
                        click.echo(f"Seeding role: {role_name}")

                # 2. Seed default Administrator user
                admin_role = Role.query.filter_by(name=RoleType.ADMIN).first()
                admin_user = User.query.filter_by(username=admin_username).first()

                if not admin_user:
                    admin_by_email = User.query.filter_by(email=admin_email).first()
                    if admin_by_email:
                        click.echo(f"Warning: User with email '{admin_email}' already exists. Skipping user seed.")
                    else:
                        admin_user = User(
                            username=admin_username,
                            email=admin_email,
                            password_hash=generate_password_hash(admin_password),
                            role=admin_role
                        )
                        db.session.add(admin_user)
                        click.echo(f"Seeding initial admin user: {admin_username}")
                else:
                    click.echo(f"Admin user '{admin_username}' already exists. Skipping user seed.")

            # Commit main transaction
            db.session.commit()

            if generated_password:
                click.echo("\n=======================================================")
                click.echo("DEVELOPMENT ADMIN CREDENTIALS GENERATED SUCCESSFULLY:")
                click.echo(f"Username: {admin_username}")
                click.echo(f"Email:    {admin_email}")
                click.echo(f"Password: {generated_password}")
                click.echo("=======================================================\n")
            else:
                click.echo("Admin seeding completed successfully.")

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error during seeding: {e}", err=True)
            raise



def _register_seed_demo_data(app):
    """Registers the flask seed-demo-data CLI command."""
    import click
    from flask.cli import with_appcontext
    from datetime import date, timedelta

    @app.cli.command("seed-demo-data")
    @with_appcontext
    def seed_demo_data():
        """
        Idempotent seeder: creates demo leave types, balances,
        leave requests, and attendance records for all active employees.
        Safe to run multiple times.
        """
        from extensions import db
        from models.employee import Employee
        from models.leave_type import LeaveType
        from models.leave_balance import LeaveBalance
        from models.leave_request import LeaveRequest, LeaveRequestStatus
        from models.attendance import Attendance, AttendanceStatus

        today = date.today()
        year = today.year

        # ----------------------------------------------------------------
        # 1. Seed leave types
        # ----------------------------------------------------------------
        leave_type_defs = [
            ("Annual Leave",    "Paid annual vacation leave.",          True,  18),
            ("Sick Leave",      "Paid leave for medical reasons.",       True,  10),
            ("Casual Leave",    "Short-notice personal leave.",          True,   6),
            ("Maternity Leave", "Paid maternity leave.",                 True,  90),
            ("Unpaid Leave",    "Leave without pay for special cases.",  False,  0),
        ]

        leave_types: dict[str, LeaveType] = {}
        try:
            for name, desc, is_paid, quota in leave_type_defs:
                lt = LeaveType.query.filter_by(name=name).first()
                if not lt:
                    lt = LeaveType(name=name, description=desc, is_paid=is_paid, annual_quota=quota)
                    db.session.add(lt)
                    click.echo(f"  [LeaveType] Created: {name}")
                else:
                    click.echo(f"  [LeaveType] Exists:  {name}")
                leave_types[name] = lt
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            click.echo(f"  ERROR seeding leave types: {e}", err=True)
            raise

        # Re-fetch to get IDs after commit
        leave_types = {lt.name: lt for lt in LeaveType.query.all()}

        # ----------------------------------------------------------------
        # 2. Allocate balances for all active employees
        # ----------------------------------------------------------------
        employees = Employee.query.filter_by(is_active=True).all()
        if not employees:
            click.echo("  [Balance] No active employees found — skipping balance seeding.")
        else:
            try:
                for emp in employees:
                    for lt in leave_types.values():
                        if lt.annual_quota == 0:
                            continue
                        existing = LeaveBalance.query.filter_by(
                            employee_id=emp.id, leave_type_id=lt.id, year=year
                        ).first()
                        if not existing:
                            bal = LeaveBalance(
                                employee_id=emp.id,
                                leave_type_id=lt.id,
                                year=year,
                                total_allocated=lt.annual_quota,
                                used=0,
                                remaining=lt.annual_quota,
                            )
                            db.session.add(bal)
                            click.echo(
                                f"  [Balance] Emp {emp.employee_code} → {lt.name}: {lt.annual_quota} days"
                            )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                click.echo(f"  ERROR seeding balances: {e}", err=True)
                raise

        # ----------------------------------------------------------------
        # 3. Sample leave request for first active employee
        # ----------------------------------------------------------------
        if employees:
            emp = employees[0]
            annual_lt = leave_types.get("Annual Leave")
            if annual_lt:
                # Leave from Monday of next week for 2 days
                days_until_monday = (7 - today.weekday()) % 7 or 7
                leave_start = today + timedelta(days=days_until_monday)
                leave_end   = leave_start + timedelta(days=1)  # 2 calendar days

                existing_req = LeaveRequest.query.filter_by(
                    employee_id=emp.id,
                    leave_type_id=annual_lt.id,
                    start_date=leave_start,
                ).first()
                if not existing_req:
                    try:
                        req = LeaveRequest(
                            employee_id=emp.id,
                            leave_type_id=annual_lt.id,
                            start_date=leave_start,
                            end_date=leave_end,
                            days_requested=2,
                            reason="Demo leave request (seeder).",
                            status=LeaveRequestStatus.PENDING,
                        )
                        db.session.add(req)
                        db.session.commit()
                        click.echo(
                            f"  [LeaveRequest] Emp {emp.employee_code}: "
                            f"{leave_start} → {leave_end} (Pending)"
                        )
                    except Exception as e:
                        db.session.rollback()
                        click.echo(f"  ERROR seeding leave request: {e}", err=True)
                else:
                    click.echo(f"  [LeaveRequest] Already exists for {emp.employee_code} on {leave_start}")

        # ----------------------------------------------------------------
        # 4. Sample attendance record for yesterday (Present)
        # ----------------------------------------------------------------
        if employees:
            emp = employees[0]
            yesterday = today - timedelta(days=1)
            existing_att = Attendance.query.filter_by(
                employee_id=emp.id, date=yesterday
            ).first()
            if not existing_att:
                try:
                    db.session.add(Attendance(
                        employee_id=emp.id,
                        date=yesterday,
                        status=AttendanceStatus.PRESENT,
                    ))
                    db.session.commit()
                    click.echo(f"  [Attendance] Emp {emp.employee_code}: {yesterday} → Present")
                except Exception as e:
                    db.session.rollback()
                    click.echo(f"  ERROR seeding attendance: {e}", err=True)
            else:
                click.echo(f"  [Attendance] Already exists for {emp.employee_code} on {yesterday}")

        click.echo("\n✅ Demo data seeding complete.")


def register_error_handlers(app):
    """Binds error templates for normal browser errors."""
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        return render_template("errors/500.html"), 500



def configure_logging(app):
    """
    Production-grade logging module.
    Automatically creates the logging directory if missing.
    Adjusts levels between development (Console/Debug) and production (Rotating File/Info).
    """
    if app.debug or app.testing:
        # Enable basic console logger in development/testing mode
        logging.basicConfig(level=logging.DEBUG)
        app.logger.setLevel(logging.DEBUG)
        app.logger.debug("Development logging active (Console output)")
    else:
        # Production config: create logs directory and write to Rotating File
        logs_dir = os.path.join(app.root_path, "logs")
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)

        log_file = os.path.join(logs_dir, "paygenius.log")
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
        ))
        file_handler.setLevel(logging.INFO)
        
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info("PayGenius AI started under Production configuration.")
