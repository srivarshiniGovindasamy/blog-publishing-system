"""Module 2 authentication and role authorization tests."""

import os
import re
import unittest
from unittest.mock import patch

from app import create_app, db
from models import Admin, Author, Reader, User
from seed import seed


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def register(self, role, email):
        token = self.csrf_token("/register")
        return self.client.post("/register", data={
            "_csrf_token": token,
            "name": "Test User",
            "email": email,
            "role": role,
            "password": "correct-horse-42",
            "confirm_password": "correct-horse-42",
        }, follow_redirects=True)

    def login(self, email, role, password="correct-horse-42"):
        token = self.csrf_token("/login")
        return self.client.post("/login", data={
            "_csrf_token": token,
            "email": email,
            "role": role,
            "password": password,
        }, follow_redirects=True)

    def test_author_registration_stores_hash_and_author_role(self):
        response = self.register("author", "author@example.com")
        self.assertIn(b"account has been created", response.data)

        with self.app.app_context():
            user = User.query.filter_by(email="author@example.com").one()
            self.assertIsInstance(user, Author)
            self.assertEqual(user.role, "author")
            self.assertNotEqual(user.password_hash, "correct-horse-42")
            self.assertTrue(user.check_password("correct-horse-42"))

    def test_reader_registration_and_admin_not_offered(self):
        page = self.client.get("/register")
        self.assertNotIn(b'value="admin"', page.data)

        response = self.register("reader", "reader@example.com")
        self.assertIn(b"account has been created", response.data)
        with self.app.app_context():
            self.assertIsInstance(
                User.query.filter_by(email="reader@example.com").one(),
                Reader,
            )

    def test_registration_rejects_admin_role_posted_directly(self):
        token = self.csrf_token("/register")
        response = self.client.post("/register", data={
            "_csrf_token": token,
            "name": "Intruder",
            "email": "admin-attempt@example.com",
            "role": "admin",
            "password": "correct-horse-42",
            "confirm_password": "correct-horse-42",
        }, follow_redirects=True)
        self.assertIn(b"Choose either Author or Reader", response.data)
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(email="admin-attempt@example.com").first())

    def test_seed_creates_only_one_admin_and_is_idempotent(self):
        with patch.dict(os.environ, {
            "ADMIN_NAME": "Seed Admin",
            "ADMIN_EMAIL": "admin@example.com",
            "ADMIN_PASSWORD": "admin-password-42",
        }, clear=False):
            seed(self.app)
            seed(self.app)

        with self.app.app_context():
            admin = Admin.query.filter_by(email="admin@example.com").one()
            self.assertEqual(Admin.query.count(), 1)
            self.assertTrue(admin.check_password("admin-password-42"))
            self.assertNotEqual(admin.password_hash, "admin-password-42")

    def test_correct_login_redirects_to_role_dashboard(self):
        self.register("author", "author@example.com")
        response = self.login("author@example.com", "author")
        self.assertIn(b"Author area", response.data)
        self.assertEqual(response.request.path, "/author")

    def test_incorrect_password_is_rejected(self):
        self.register("reader", "reader@example.com")
        response = self.login("reader@example.com", "reader", "wrong-password")
        self.assertIn(b"email or password is incorrect", response.data)
        self.assertEqual(response.request.path, "/login")

    def test_wrong_selected_role_is_rejected_clearly(self):
        self.register("author", "author@example.com")
        response = self.login("author@example.com", "reader")
        self.assertIn(b"selected role does not match", response.data)
        self.assertEqual(response.request.path, "/login")

    def test_logout_clears_login_session(self):
        self.register("reader", "reader@example.com")
        self.login("reader@example.com", "reader")
        token = self.csrf_token("/reader")
        response = self.client.post("/logout", data={"_csrf_token": token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/login")
        self.assertEqual(self.client.get("/reader").status_code, 302)

    def test_other_role_cannot_access_protected_dashboard(self):
        self.register("reader", "reader@example.com")
        self.login("reader@example.com", "reader")
        self.assertEqual(self.client.get("/author").status_code, 403)
        self.assertEqual(self.client.get("/admin").status_code, 403)

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get("/author")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith("/login?"))

    def test_authentication_posts_require_csrf_token(self):
        response = self.client.post("/login", data={
            "email": "nobody@example.com",
            "password": "incorrect",
            "role": "reader",
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
