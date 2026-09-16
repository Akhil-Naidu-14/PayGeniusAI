import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

class Config:
    """Base configuration class with default values."""
    # Security config
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        # Provide a fallback for local development, but force set in production
        SECRET_KEY = "paygenius-default-secret-key-please-change-in-production"

    # Database config
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    if SQLALCHEMY_DATABASE_URI:
        # Normalize PostgreSQL URL schema for SQLAlchemy 1.4+
        if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
            SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    else:
        # Default SQLite database
        SQLALCHEMY_DATABASE_URI = "sqlite:///paygenius.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Cookie security configurations
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # Set to True under HTTPS (Production)
    SESSION_COOKIE_SAMESITE = "Lax"


class DevelopmentConfig(Config):
    """Development environment configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production environment configuration."""
    DEBUG = False
    
    # Enforce strict secret key validation in production
    @property
    def SECRET_KEY(self):
        key = os.environ.get("SECRET_KEY")
        if not key or key == "paygenius-default-secret-key-please-change-in-production":
            raise ValueError(
                "CRITICAL: SECRET_KEY environment variable is not configured or uses insecure default "
                "in a production environment! Please set a strong, unique secret key."
            )
        return key

    # Force HTTPS only session cookies in production
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    """Testing environment configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    LOGIN_DISABLED = False





# Map configuration names to classes
config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig
}
