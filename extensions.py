from sqlalchemy import MetaData
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

# Setup database constraint naming convention for cross-DB portability (SQLite/Postgres)
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Instantiate SQLAlchemy database wrapper with metadata naming conventions & pool options
db = SQLAlchemy(
    metadata=MetaData(naming_convention=naming_convention),
    engine_options={
        "pool_pre_ping": True,
        "pool_recycle": 300
    }
)

# Instantiate database migration engine
migrate = Migrate()

# Instantiate user session manager with enterprise security settings
login_manager = LoginManager()
login_manager.session_protection = "strong"
login_manager.login_message_category = "warning"

# Instantiate cross-site request forgery protection
csrf = CSRFProtect()
