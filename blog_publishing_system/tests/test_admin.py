"""Admin dashboard and account-management behavior tests."""

import re
import unittest

from app import create_app, db
from models import Admin, Author, Post, Reader, User


class AdminManagementTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "admin-test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            self.admin = Admin(name="Protected Admin", email="admin@example.com")
            self.admin.set_password("admin-password-42")
            self.author = Author(name="Test Author", email="author@example.com")
            self.author.set_password("author-password-42")
            self.reader = Reader(name="Test Reader", email="reader@example.com")
            self.reader.set_password("reader-password-42")
            db.session.add_all([self.admin, self.author, self.reader])
            db.session.commit()
            self.admin_id = self.admin.id
            self.author_id = self.author.id
            self.reader_id = self.reader.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _csrf_token(self):
        response = self.client.get("/admin/users")
        if response.status_code == 302:
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def _login(self, role="admin", email="admin@example.com"):
        token = self._csrf_token()
        self.csrf_token_value = token
        return self.client.post("/login", data={
            "_csrf_token": token,
            "email": email,
            "password": f"{role}-password-42",
            "role": role,
        })

    def test_admin_dashboard_shows_database_statistics_and_admin_navigation(self):
        response = self._login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/admin/dashboard")

        dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Total Users", dashboard.data)
        self.assertIn(b">3<", dashboard.data)
        self.assertIn(b"User Management", dashboard.data)

        users = self.client.get("/admin/users")
        self.assertEqual(users.status_code, 200)
        self.assertIn(b"Protected administrator", users.data)
        self.assertIn(b"User Management", users.data)
        self.assertNotIn(b'href="/" class="nav-link active">Home</a>', users.data)

    def test_non_admins_cannot_access_admin_pages(self):
        self._login("reader", "reader@example.com")
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)
        self.client.post(
            "/logout",
            data={"_csrf_token": self.csrf_token_value},
        )
        self._login("author", "author@example.com")
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)

    def test_role_can_change_reader_to_author_and_author_to_reader(self):
        self._login()
        token = self._csrf_token()
        response = self.client.post(
            f"/admin/users/{self.reader_id}/role",
            data={"_csrf_token": token, "role": "author"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            changed_reader = db.session.get(User, self.reader_id)
            self.assertIsInstance(changed_reader, Author)
            self.assertEqual(changed_reader.role, "author")

        response = self.client.post(
            f"/admin/users/{self.author_id}/role",
            data={"_csrf_token": token, "role": "reader"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            changed_author = db.session.get(User, self.author_id)
            self.assertIsInstance(changed_author, Reader)
            self.assertEqual(changed_author.role, "reader")

    def test_admin_cannot_demote_or_delete_administrator(self):
        self._login()
        token = self._csrf_token()
        role_response = self.client.post(
            f"/admin/users/{self.admin_id}/role",
            data={"_csrf_token": token, "role": "reader"},
            follow_redirects=True,
        )
        delete_response = self.client.post(
            f"/admin/users/{self.admin_id}/delete",
            data={"_csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn(b"protected", role_response.data)
        self.assertIn(b"protected", delete_response.data)
        with self.app.app_context():
            self.assertIsInstance(db.session.get(User, self.admin_id), Admin)

    def test_deletion_removes_only_accounts_without_associated_records(self):
        self._login()
        token = self._csrf_token()
        with self.app.app_context():
            author = db.session.get(User, self.author_id)
            db.session.add(Post(
                title="Owned story",
                content="This story prevents account deletion.",
                status=Post.STATUS_DRAFT,
                author=author,
            ))
            db.session.commit()

        blocked = self.client.post(
            f"/admin/users/{self.author_id}/delete",
            data={"_csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn(b"cannot be deleted", blocked.data)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(User, self.author_id))

        removed = self.client.post(
            f"/admin/users/{self.reader_id}/delete",
            data={"_csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn(b"deleted successfully", removed.data)
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, self.reader_id))
            self.assertIsNotNone(Post.query.filter_by(author_id=self.author_id).first())

    def test_role_change_is_blocked_when_it_would_detach_owned_posts(self):
        self._login()
        token = self._csrf_token()
        with self.app.app_context():
            author = db.session.get(User, self.author_id)
            db.session.add(Post(
                title="Owned story",
                content="Changing this role would detach the story.",
                status=Post.STATUS_DRAFT,
                author=author,
            ))
            db.session.commit()

        response = self.client.post(
            f"/admin/users/{self.author_id}/role",
            data={"_csrf_token": token, "role": "reader"},
            follow_redirects=True,
        )
        self.assertIn(b"role cannot be changed", response.data)
        with self.app.app_context():
            self.assertIsInstance(db.session.get(User, self.author_id), Author)


if __name__ == "__main__":
    unittest.main()
