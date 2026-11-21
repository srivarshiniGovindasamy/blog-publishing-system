"""
config.py — Application Configuration
=======================================
Loads environment variables and builds the MySQL connection URI
for SQLAlchemy.  Falls back to sensible XAMPP defaults but NEVER
silently switches to SQLite.
"""

import os
import secrets
from dotenv import load_dotenv

# Load variables from .env file (if it exists)
load_dotenv()


class Config:
    """Base configuration loaded from environment variables."""

    # ----- Flask -----
    # In development, generate a process-local key if no secret was configured.
    # Set FLASK_SECRET_KEY in .env for sessions that survive application restarts.
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
    DEBUG = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False").lower() in (
        "true", "1", "yes"
    )
    COMMENT_ABUSIVE_TERMS = tuple(
        term.strip()
        for term in os.getenv(
            "COMMENT_ABUSIVE_TERMS",
            "stupid,useless,idiot,moron,dumbass,jackass,asshole,bastard,"
            "fucking,fuck,shit,bitch",
        ).split(",")
        if term.strip()
    )

    # ----- MySQL Database -----
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_NAME = os.getenv("DB_NAME", "blog_publishing_system")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    # Build the MySQL connection URI
    # Format: mysql+pymysql://user:password@host:port/database
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    # Disable the Flask-SQLAlchemy event system (saves resources)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
