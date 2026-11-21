"""Module 3 post ownership and categorization tests."""

import re
import unittest

from app import create_app, db
from models import Author, Category, Post, Revision, Tag


class PostManagementTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
        self._register_author("author-one@example.com", "Author One")
        self._register_author("author-two@example.com", "Author Two")
        self._login("author-one@example.com")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def _register_author(self, email, name):
        token = self._csrf_token("/register")
        response = self.client.post("/register", data={
            "_csrf_token": token,
            "name": name,
            "email": email,
            "role": "author",
            "password": "correct-horse-42",
            "confirm_password": "correct-horse-42",
        })
        self.assertEqual(response.status_code, 302)

    def _login(self, email):
        token = self._csrf_token("/login")
        response = self.client.post("/login", data={
            "_csrf_token": token,
            "email": email,
            "role": "author",
            "password": "correct-horse-42",
        })
        self.assertEqual(response.status_code, 302)
        return response

    def _logout(self):
        token = self._csrf_token("/author")
        response = self.client.post("/logout", data={"_csrf_token": token})
        self.assertEqual(response.status_code, 302)

    def _create_post(self, title, content, categories="", tags=""):
        token = self._csrf_token("/author/posts/new")
        return self.client.post("/author/posts/new", data={
            "_csrf_token": token,
            "title": title,
            "content": content,
            "categories": categories,
            "tags": tags,
        })

    def test_author_creates_draft_with_category_and_multiple_tags(self):
        response = self._create_post(
            "First post",
            "A useful article about writing.",
            "Programming, Software Engineering",
            "Python, Flask",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/author")

        with self.app.app_context():
            author = Author.query.filter_by(email="author-one@example.com").one()
            post = Post.query.one()
            self.assertEqual(post.author_id, author.id)
            self.assertIs(post.author, author)
            self.assertEqual(post.status, Post.STATUS_DRAFT)
            self.assertEqual(
                {category.name for category in post.categories},
                {"Programming", "Software Engineering"},
            )
            self.assertEqual({tag.name for tag in post.tags}, {"Python", "Flask"})
            self.assertEqual(Category.query.count(), 10)
            self.assertEqual(Tag.query.count(), 10)

    def test_edit_saves_changes_and_replaces_category_and_tag_assignments(self):
        self._create_post("Old title", "Old content", "Technology", "Python")
        with self.app.app_context():
            post_id = Post.query.one().id

        token = self._csrf_token(f"/author/posts/{post_id}/edit")
        response = self.client.post(
            f"/author/posts/{post_id}/edit",
            data={
                "_csrf_token": token,
                "title": "Updated title",
                "content": "Updated content",
                "categories": "Data Science",
                "tags": "JavaScript, SQL",
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(post.title, "Updated title")
            self.assertEqual(post.content, "Updated content")
            self.assertEqual(post.status, Post.STATUS_DRAFT)
            self.assertEqual(
                {category.name for category in post.categories},
                {"Data Science"},
            )
            self.assertEqual(
                {tag.name for tag in post.tags},
                {"JavaScript", "SQL"},
            )

    def test_author_cannot_create_custom_categories_or_tags(self):
        category_response = self._create_post(
            "Custom taxonomy story",
            "The author must choose from the predefined values.",
            "Custom Category",
            "Python",
        )
        self.assertEqual(category_response.status_code, 200)
        self.assertIn(
            b"Choose categories from the predefined list.",
            category_response.data,
        )

        tag_response = self._create_post(
            "Custom tag story",
            "Tags must also come from the predefined values.",
            "Programming",
            "Custom Tag",
        )
        self.assertEqual(tag_response.status_code, 200)
        self.assertIn(b"Choose tags from the predefined list.", tag_response.data)
        with self.app.app_context():
            self.assertEqual(Post.query.count(), 0)
            self.assertIsNone(Category.query.filter_by(name="Custom Category").first())
            self.assertIsNone(Tag.query.filter_by(name="Custom Tag").first())

    def test_draft_publish_archive_lifecycle_and_public_visibility(self):
        self._create_post("Lifecycle story", "The story is ready to publish.")
        with self.app.app_context():
            post_id = Post.query.one().id
            self.assertEqual(db.session.get(Post, post_id).status, Post.STATUS_DRAFT)

        edit_token = self._csrf_token(f"/author/posts/{post_id}/edit")
        response = self.client.post(
            f"/author/posts/{post_id}/edit",
            data={
                "_csrf_token": edit_token,
                "title": "Edited lifecycle story",
                "content": "The updated story is ready.",
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Post, post_id).status,
                Post.STATUS_DRAFT,
            )

        publish_token = self._csrf_token("/author")
        response = self.client.post(
            f"/author/posts/{post_id}/publish",
            data={"_csrf_token": publish_token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(post.status, Post.STATUS_PUBLISHED)
            published_updated_at = post.updated_at

        response = self.client.get("/")
        self.assertIn(b"Edited lifecycle story", response.data)
        response = self.client.get(f"/posts/{post_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The updated story is ready.", response.data)

        archive_token = self._csrf_token("/author")
        response = self.client.post(
            f"/author/posts/{post_id}/archive",
            data={"_csrf_token": archive_token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(post.status, Post.STATUS_ARCHIVED)
            self.assertGreaterEqual(post.updated_at, published_updated_at)

        response = self.client.get("/")
        self.assertNotIn(b"Edited lifecycle story", response.data)
        self.assertEqual(self.client.get(f"/posts/{post_id}").status_code, 404)
        dashboard = self.client.get("/author")
        self.assertIn(b"Archived", dashboard.data)
        self.assertIn(b"View</a>", dashboard.data)

    def test_cannot_skip_or_reverse_lifecycle_transitions(self):
        self._create_post("Transition story", "Keep status transitions ordered.")
        with self.app.app_context():
            post = Post.query.one()
            self.assertFalse(post.archive())
            self.assertTrue(post.publish())
            self.assertFalse(post.publish())
            self.assertTrue(post.archive())
            self.assertFalse(post.publish())
            self.assertFalse(post.archive())

    def test_publish_with_empty_title_or_content_keeps_post_as_draft(self):
        self._create_post("Valid title", "Valid content")
        with self.app.app_context():
            post_id = Post.query.one().id

        for title, content in (("", "Valid content"), ("Valid title", "")):
            token = self._csrf_token(f"/author/posts/{post_id}/edit")
            response = self.client.post(
                f"/author/posts/{post_id}/edit",
                data={
                    "_csrf_token": token,
                    "title": title,
                    "content": content,
                    "action": "publish",
                },
            )
            self.assertEqual(response.status_code, 200)
            with self.app.app_context():
                post = db.session.get(Post, post_id)
                self.assertEqual(post.status, Post.STATUS_DRAFT)
                self.assertEqual(post.title, "Valid title")
                self.assertEqual(post.content, "Valid content")

    def test_editing_a_published_post_keeps_it_published(self):
        self._create_post("Published story", "Original published content")
        with self.app.app_context():
            post_id = Post.query.one().id
        publish_token = self._csrf_token("/author")
        self.client.post(
            f"/author/posts/{post_id}/publish",
            data={"_csrf_token": publish_token},
        )

        edit_token = self._csrf_token(f"/author/posts/{post_id}/edit")
        response = self.client.post(
            f"/author/posts/{post_id}/edit",
            data={
                "_csrf_token": edit_token,
                "title": "Edited published story",
                "content": "Updated published content",
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(post.status, Post.STATUS_PUBLISHED)
            self.assertEqual(post.title, "Edited published story")

    def test_initial_save_and_each_edit_create_full_content_revisions(self):
        self._create_post("Revision story", "Snapshot one.")
        with self.app.app_context():
            post = Post.query.one()
            post_id = post.id
            self.assertEqual(
                [(revision.revision_number, revision.content) for revision in post.revisions],
                [(1, "Snapshot one.")],
            )

        self._edit_content(post_id, "Snapshot two.")
        self._edit_content(post_id, "Snapshot three.")
        self._edit_content(post_id, "Snapshot four.")

        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(
                [(revision.revision_number, revision.content) for revision in post.revisions],
                [
                    (4, "Snapshot four."),
                    (3, "Snapshot three."),
                    (2, "Snapshot two."),
                    (1, "Snapshot one."),
                ],
            )

        history = self.client.get(f"/author/posts/{post_id}/edit")
        self.assertEqual(history.status_code, 200)
        page = history.get_data(as_text=True)
        self.assertLess(page.index("Revision 4"), page.index("Revision 3"))
        self.assertLess(page.index("Revision 3"), page.index("Revision 2"))
        self.assertLess(page.index("Revision 2"), page.index("Revision 1"))

    def _edit_content(self, post_id, content):
        token = self._csrf_token(f"/author/posts/{post_id}/edit")
        return self.client.post(
            f"/author/posts/{post_id}/edit",
            data={
                "_csrf_token": token,
                "title": "Revision story",
                "content": content,
                "action": "save",
            },
        )

    def test_rollback_restores_content_and_appends_new_revision_without_changing_status(self):
        self._create_post("Rollback story", "Original snapshot.")
        with self.app.app_context():
            post_id = Post.query.one().id
        self._edit_content(post_id, "Second snapshot.")
        self._edit_content(post_id, "Third snapshot.")
        publish_token = self._csrf_token("/author")
        self.client.post(
            f"/author/posts/{post_id}/publish",
            data={"_csrf_token": publish_token},
        )

        with self.app.app_context():
            post = db.session.get(Post, post_id)
            revision_one = next(
                revision for revision in post.revisions
                if revision.revision_number == 1
            )
            original_revision_id = revision_one.id

        rollback_url = f"/author/posts/{post_id}/revisions/{original_revision_id}/rollback"
        token = self._csrf_token(f"/author/posts/{post_id}/edit")
        response = self.client.post(rollback_url, data={"_csrf_token": token})
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(post.content, "Original snapshot.")
            self.assertEqual(post.status, Post.STATUS_PUBLISHED)
            self.assertEqual(
                [(revision.revision_number, revision.content) for revision in post.revisions],
                [
                    (4, "Original snapshot."),
                    (3, "Third snapshot."),
                    (2, "Second snapshot."),
                    (1, "Original snapshot."),
                ],
            )
            self.assertEqual(db.session.get(Revision, original_revision_id).content, "Original snapshot.")

    def test_rollback_keeps_draft_status(self):
        self._create_post("Draft rollback", "Original draft.")
        with self.app.app_context():
            post = Post.query.one()
            post_id = post.id
            revision_id = post.revisions[0].id

        self._edit_content(post_id, "Changed draft.")
        token = self._csrf_token(f"/author/posts/{post_id}/edit")
        response = self.client.post(
            f"/author/posts/{post_id}/revisions/{revision_id}/rollback",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            post = db.session.get(Post, post_id)
            self.assertEqual(post.status, Post.STATUS_DRAFT)
            self.assertEqual(post.content, "Original draft.")
            self.assertEqual(len(post.revisions), 3)

    def test_revision_history_and_rollback_require_post_ownership(self):
        self._create_post("First author's post", "First author's content")
        self._create_post("Second post same owner", "Another distinct post.")
        with self.app.app_context():
            post = Post.query.filter_by(title="First author's post").one()
            post_id = post.id
            revision_id = post.revisions[0].id
            other_post_id = Post.query.filter_by(
                title="Second post same owner",
            ).one().id

        self._logout()
        self._login("author-two@example.com")
        self.assertEqual(
            self.client.get(f"/author/posts/{post_id}/edit").status_code,
            404,
        )
        token = self._csrf_token("/author")
        self.assertEqual(
            self.client.post(
                f"/author/posts/{post_id}/revisions/{revision_id}/rollback",
                data={"_csrf_token": token},
            ).status_code,
            404,
        )

        self._logout()
        self._login("author-one@example.com")
        token = self._csrf_token("/author")
        self.assertEqual(
            self.client.post(
                f"/author/posts/{other_post_id}/revisions/{revision_id}/rollback",
                data={"_csrf_token": token},
            ).status_code,
            404,
        )

    def test_post_deletion_cascades_to_its_revisions(self):
        self._create_post("Delete cascade", "Keep revisions dependent on post.")
        with self.app.app_context():
            post = Post.query.one()
            post_id = post.id
            self.assertEqual(len(post.revisions), 1)
            revision_id = post.revisions[0].id
            db.session.delete(post)
            db.session.commit()
            self.assertIsNone(db.session.get(Revision, revision_id))

    def test_author_cannot_publish_or_archive_another_authors_post(self):
        self._create_post("Protected lifecycle", "Author one owns this.")
        with self.app.app_context():
            post_id = Post.query.one().id

        self._logout()
        self._login("author-two@example.com")
        token = self._csrf_token("/author")
        self.assertEqual(
            self.client.post(
                f"/author/posts/{post_id}/publish",
                data={"_csrf_token": token},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/author/posts/{post_id}/archive",
                data={"_csrf_token": token},
            ).status_code,
            404,
        )
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Post, post_id).status,
                Post.STATUS_DRAFT,
            )

    def test_author_dashboard_lists_only_the_logged_in_authors_posts(self):
        self._create_post("Author One Post", "Owned by first author")
        self._logout()
        self._login("author-two@example.com")
        self._create_post("Author Two Post", "Owned by second author")

        response = self.client.get("/author")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Author Two Post", response.data)
        self.assertNotIn(b"Author One Post", response.data)

    def test_categories_and_tags_are_reused_across_posts(self):
        self._create_post("First", "First body", "Programming", "Python")
        self._create_post("Second", "Second body", "programming", "PYTHON")

        with self.app.app_context():
            self.assertEqual(Category.query.count(), 10)
            self.assertEqual(Tag.query.count(), 10)
            category = Category.query.filter_by(name="Programming").one()
            tag = Tag.query.filter_by(name="Python").one()
            self.assertEqual(len(category.posts), 2)
            self.assertEqual(len(tag.posts), 2)

    def test_author_cannot_view_or_edit_another_authors_post(self):
        self._create_post("Private post", "This belongs to author one")
        with self.app.app_context():
            post_id = Post.query.one().id

        self._logout()
        self._login("author-two@example.com")
        response = self.client.get(f"/author/posts/{post_id}/edit")
        self.assertEqual(response.status_code, 404)

        token = self._csrf_token("/author/posts/new")
        response = self.client.post(
            f"/author/posts/{post_id}/edit",
            data={
                "_csrf_token": token,
                "title": "Hijacked title",
                "content": "Attempted unauthorized edit",
            },
        )
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            self.assertEqual(db.session.get(Post, post_id).title, "Private post")

    def test_title_and_content_are_required(self):
        response = self._create_post("", "")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter a title", response.data)
        response = self._create_post("Has a title", "")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Post content cannot be empty", response.data)
        with self.app.app_context():
            self.assertEqual(Post.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
