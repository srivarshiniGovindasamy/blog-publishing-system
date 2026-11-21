"""
seed.py — Database Seeder
===========================
Creates the schema, initializes predefined categories and tags, and can seed
one controlled administrator account.
Run this script after creating the MySQL database.

Usage:
    python seed.py
"""

import os

from sqlalchemy import inspect, text

from app import create_app, db
from models import Admin
from services.taxonomy import ensure_predefined_terms


def seed(app=None):
    """Create the schema and, when configured, one idempotent admin account."""
    app = app or create_app()
    with app.app_context():
        db.create_all()
        if "moderation_reason" not in {
            column["name"] for column in inspect(db.engine).get_columns("comments")
        }:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE comments "
                    "ADD COLUMN moderation_reason VARCHAR(255) NULL"
                ))
        print("All database tables created successfully.")
        ensure_predefined_terms()

        admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        admin_name = os.getenv("ADMIN_NAME", "Administrator").strip()

        if not admin_email and not admin_password:
            return
        if not admin_email or not admin_password:
            raise ValueError("Set both ADMIN_EMAIL and ADMIN_PASSWORD to seed an admin.")
        if len(admin_password) < 8 or len(admin_password) > 128:
            raise ValueError("ADMIN_PASSWORD must be between 8 and 128 characters.")

        existing_admin = Admin.query.first()
        if existing_admin:
            if existing_admin.email == admin_email:
                print("The configured admin account already exists; no changes made.")
                return
            raise RuntimeError(
                "An admin account already exists. Refusing to create another one."
            )

        if Admin.query.filter_by(email=admin_email).first():
            print("The configured admin account already exists; no changes made.")
            return

        from models import User
        if User.query.filter_by(email=admin_email).first():
            raise RuntimeError("The configured admin email belongs to a non-admin account.")
        if not admin_name or len(admin_name) > 120:
            raise ValueError("ADMIN_NAME must be between 1 and 120 characters.")

        admin = Admin(name=admin_name, email=admin_email)
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        print("Admin account created successfully.")


if __name__ == "__main__":
    seed()
