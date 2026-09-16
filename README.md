# PayGenius AI
> **Smart Payroll. Intelligent Workforce.**

PayGenius AI is a production-grade, highly scalable Flask 3+ web application framework built using professional enterprise design principles, strict separation of concerns, and robust configurations.

---

## Architecture Overview

This project employs the **Application Factory Pattern** paired with a **Feature-Modular Blueprint Layout** and a centralized service layer, ensuring scalability for additional future enterprise modules (e.g., authentication, attendance tracker, salary computations).

```
paygenius-ai/
│
├── blueprints/             # Feature Blueprints
│   └── main/               # Main Blueprint Module
│       ├── __init__.py     # Blueprint definition
│       ├── routes.py       # Slim controller routes (logic-free)
│       └── services.py     # Pure Service class (business logic queries)
│
├── models/                 # Database ORM Schemas
│   ├── __init__.py         # Reusable abstract BaseModel (id, timestamps)
│   └── user.py             # User DB model inheriting BaseModel & UserMixin
│
├── static/                 # Static Assets
│   └── css/
│       └── style.css       # Premium Dark UI Stylesheet
│
├── templates/              # Jinja2 Layout Templates
│   ├── errors/             # Error Page Overrides
│   │   ├── 404.html
│   │   └── 500.html
│   ├── base.html           # Main UI Shell & Bootstrap 5
│   └── index.html          # Dashboard landing interface
│
├── app.py                  # create_app Application Factory Setup
├── config.py               # Separation of Dev, Prod, and Test configs
├── extensions.py           # Global initialization registry (SQLAlchemy, LoginManager, etc.)
├── wsgi.py                 # WSGI Entry point
├── requirements.txt        # PIP Dependency requirements
├── .env                    # Active Environment Variables
└── .env.example            # Environment variables template
```

---

## Architectural Rules Implemented

1. **Separation of Concerns**: Routes contain no business logic. Route definitions immediately delegate data gathering and mutations to static/class methods defined inside Service classes (e.g., `MainService` in `blueprints/main/services.py`).
2. **Abstract BaseModel**: All database entities inherit from a global abstract `BaseModel` located in [models/\_\_init\_\_.py](file:///d:/College/4-1/my/Project/paygenius-ai/models/__init__.py), which pre-packages standard audited data elements (`id`, `created_at`, `updated_at`, `is_active`).
3. **No Request Dependents inside Services**: Services act on raw parameters or database queries. They do not access the Flask `request` or global request proxies, keeping them testable in isolation.
4. **Production-Grade Logging**: Auto-creates `logs/` directory and writes rotating files (`paygenius.log`) under `ProductionConfig`.
5. **Secure Middleware**: Dynamically appends essential secure browser response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) to intercept clickjacking and MIME injection attempts.
6. **SQL / Postgres Portability**: Features pre-configured PostgreSQL parsing support that normalizes URL bindings (`postgres://` to `postgresql://`) while defaulting to local SQLite.

---

## Installation & Setup

### 1. Configure the Virtual Environment
Activate the pre-existing python environment:
```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
```

### 2. Verify Requirements
All required packages (Flask 3, SQLAlchemy, Migrate, WTForms, python-dotenv) are detailed in `requirements.txt`. Install using:
```bash
pip install -r requirements.txt
```

### 3. Setup Environment variables
Create a `.env` file by copying the template:
```bash
copy .env.example .env
```

Ensure the `.env` settings map to your developer target:
- `FLASK_APP=wsgi.py`
- `FLASK_ENV=development`
- `SECRET_KEY=your-secure-secret-key-here`

---

## Running the Application

### Initialize Database Migrations
Run the Flask-Migrate database setup to create SQLite tables:
```bash
flask --app app:create_app db init
flask --app app:create_app db migrate -m "Initialize database models"
flask --app app:create_app db upgrade
```

### Launch Development Server
Startup the application server:
```bash
flask --app app:create_app run
```
Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your web browser.
