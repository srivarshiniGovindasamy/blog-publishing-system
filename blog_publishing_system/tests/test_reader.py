"""Reader feed, article visibility, and comment behavior tests."""

import re
import unittest
from datetime import datetime

from app import create_app, db
from models import Admin, Author, Bookmark, Comment, Post, Reader, ReadingHistory


class ReaderExperienceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "reader-test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            self.author = Author(name="Feed Author", email="feed-author@example.com")
            self.author.set_password("feed-author-password")
            self.reader = Reader(name="Feed Reader", email="feed-reader@example.com")
            self.reader.set_password("feed-reader-password")
            self.other_reader = Reader(
                name="Other Reader",
                email="other-reader@example.com",
            )
            self.other_reader.set_password("other-reader-password")
            self.admin = Admin(name="Feed Admin", email="feed-admin@example.com")
            self.admin.set_password("feed-admin-password")
            db.session.add_all([
                self.author,
                self.reader,
                self.other_reader,
                self.admin,
            ])
            db.session.commit()

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

    def _login(self, email, password, role):
        token = self._csrf_token("/login")
        return self.client.post("/login", data={
            "_csrf_token": token,
            "email": email,
            "password": password,
            "role": role,
        })

    def _logout(self):
        token = self._csrf_token("/")
        return self.client.post("/logout", data={"_csrf_token": token})

    def _make_post(self, title, content, status):
        with self.app.app_context():
            author = Author.query.filter_by(email="feed-author@example.com").one()
            post = Post(
                title=title,
                content=content,
                author=author,
                status=Post.STATUS_DRAFT,
            )
            db.session.add(post)
            db.session.commit()
            if status == Post.STATUS_PUBLISHED:
                self.assertTrue(post.publish())
            elif status == Post.STATUS_ARCHIVED:
                self.assertTrue(post.publish())
                self.assertTrue(post.archive())
            db.session.commit()
            return post.id

    def test_public_feed_shows_published_only_and_has_an_empty_state(self):
        self._make_post("Visible published story", "Published body", Post.STATUS_PUBLISHED)
        self._make_post("Hidden draft story", "Draft body", Post.STATUS_DRAFT)
        self._make_post("Hidden archived story", "Archived body", Post.STATUS_ARCHIVED)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Visible published story", response.data)
        self.assertNotIn(b"Hidden draft story", response.data)
        self.assertNotIn(b"Hidden archived story", response.data)
        self.assertIn(b"public-story-card-link", response.data)
        self.assertIn(b"Read", response.data)

        with self.app.app_context():
            Post.query.delete()
            db.session.commit()
        response = self.client.get("/")
        self.assertIn(b"No published posts yet.", response.data)

    def test_article_displays_full_story_metadata_and_calculated_reading_time(self):
        content = " ".join(f"word{index}" for index in range(500))
        post_id = self._make_post(
            "Long published article",
            content,
            Post.STATUS_PUBLISHED,
        )
        response = self.client.get(f"/posts/{post_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Long published article", response.data)
        self.assertIn(b"Feed Author", response.data)
        self.assertIn(b"3 min read", response.data)
        self.assertIn(b"word499", response.data)

    def test_reader_can_comment_and_approved_comment_is_visible(self):
        post_id = self._make_post(
            "Commentable story",
            "Readers can discuss this published story.",
            Post.STATUS_PUBLISHED,
        )
        self._login("feed-reader@example.com", "feed-reader-password", "reader")
        token = self._csrf_token(f"/posts/{post_id}")
        response = self.client.post(
            f"/posts/{post_id}/comments",
            data={
                "_csrf_token": token,
                "content": "A thoughtful reader comment.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your comment has been published.", response.data)

        with self.app.app_context():
            comment = Comment.query.one()
            self.assertEqual(comment.content, "A thoughtful reader comment.")
            self.assertTrue(comment.approved)
            self.assertEqual(comment.moderation_reason, "Comment approved.")
            self.assertEqual(comment.reader.email, "feed-reader@example.com")
            self.assertEqual(comment.post_id, post_id)

        response = self.client.get(f"/posts/{post_id}")
        self.assertIn(b"Feed Reader", response.data)
        self.assertIn(b"A thoughtful reader comment.", response.data)

    def test_anonymous_visitor_is_prompted_to_log_in_as_reader(self):
        post_id = self._make_post(
            "Visitor comment story",
            "Commenting requires Reader sign in.",
            Post.STATUS_PUBLISHED,
        )
        token = self._csrf_token("/login")
        response = self.client.post(
            f"/posts/{post_id}/comments",
            data={"_csrf_token": token, "content": "A visitor comment."},
            follow_redirects=True,
        )
        self.assertEqual(response.request.path, "/login")
        self.assertIn(b"Please log in as a Reader to comment.", response.data)
        with self.app.app_context():
            self.assertEqual(Comment.query.count(), 0)

    def test_author_and_admin_cannot_comment(self):
        post_id = self._make_post(
            "Reader-only comments",
            "Only Readers may submit comments.",
            Post.STATUS_PUBLISHED,
        )
        for email, password, role in (
            ("feed-author@example.com", "feed-author-password", "author"),
            ("feed-admin@example.com", "feed-admin-password", "admin"),
        ):
            self._login(email, password, role)
            token = self._csrf_token(f"/posts/{post_id}")
            response = self.client.post(
                f"/posts/{post_id}/comments",
                data={"_csrf_token": token, "content": "Not allowed."},
            )
            self.assertEqual(response.status_code, 403)
            self._logout()
        with self.app.app_context():
            self.assertEqual(Comment.query.count(), 0)

    def test_comment_validation_and_unapproved_comments_are_not_public(self):
        post_id = self._make_post(
            "Comment validation story",
            "Comments require a non-empty reasonable-length body.",
            Post.STATUS_PUBLISHED,
        )
        self._login("feed-reader@example.com", "feed-reader-password", "reader")
        token = self._csrf_token(f"/posts/{post_id}")
        response = self.client.post(
            f"/posts/{post_id}/comments",
            data={"_csrf_token": token, "content": "  "},
            follow_redirects=True,
        )
        self.assertIn(b"Write a comment before submitting.", response.data)

        token = self._csrf_token(f"/posts/{post_id}")
        response = self.client.post(
            f"/posts/{post_id}/comments",
            data={
                "_csrf_token": token,
                "content": "x" * (Comment.MAX_CONTENT_LENGTH + 1),
            },
            follow_redirects=True,
        )
        self.assertIn(b"Comments must be", response.data)

        with self.app.app_context():
            post = db.session.get(Post, post_id)
            db.session.add(Comment(
                post=post,
                reader=Reader.query.filter_by(email="feed-reader@example.com").one(),
                content="Pending and hidden",
                approved=False,
            ))
            db.session.commit()
        response = self.client.get(f"/posts/{post_id}")
        self.assertNotIn(b"Pending and hidden", response.data)

    def test_reader_cannot_access_author_management(self):
        self._login("feed-reader@example.com", "feed-reader-password", "reader")
        self.assertEqual(self.client.get("/author").status_code, 403)
        self.assertEqual(self.client.get("/admin").status_code, 403)

    def test_reader_bookmarks_and_removes_published_posts_without_duplicates(self):
        post_id = self._make_post(
            "Bookmarkable story",
            "Save this story for later.",
            Post.STATUS_PUBLISHED,
        )
        self._login("feed-reader@example.com", "feed-reader-password", "reader")

        response = self.client.get(f"/posts/{post_id}")
        self.assertIn(b"Bookmark", response.data)
        token = self._csrf_token(f"/posts/{post_id}")
        for _ in range(2):
            response = self.client.post(
                f"/posts/{post_id}/bookmark",
                data={"_csrf_token": token},
            )
            self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            self.assertEqual(Bookmark.query.count(), 1)
        dashboard = self.client.get("/reader")
        self.assertIn(b"Bookmarkable story", dashboard.data)
        self.assertIn(b"Remove bookmark", dashboard.data)
        self.assertIn(b"Reader Area", dashboard.data)

        token = self._csrf_token("/reader")
        response = self.client.post(
            f"/posts/{post_id}/bookmark/remove",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Bookmark.query.count(), 0)
        self.assertNotIn(b"Remove bookmark", self.client.get("/reader").data)

    def test_anonymous_can_read_approved_comments_but_cannot_bookmark(self):
        post_id = self._make_post(
            "Public comments story",
            "This article is public.",
            Post.STATUS_PUBLISHED,
        )
        with self.app.app_context():
            post = db.session.get(Post, post_id)
            db.session.add(Comment(
                post=post,
                reader=Reader.query.filter_by(
                    email="feed-reader@example.com",
                ).one(),
                content="A public approved comment.",
                approved=True,
            ))
            db.session.commit()

        response = self.client.get(f"/posts/{post_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A public approved comment.", response.data)
        token = self._csrf_token(f"/posts/{post_id}")
        response = self.client.post(
            f"/posts/{post_id}/bookmark",
            data={"_csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.request.path, "/login")
        self.assertIn(b"Please log in as a Reader to bookmark stories.", response.data)
        with self.app.app_context():
            self.assertEqual(Bookmark.query.count(), 0)
            self.assertEqual(ReadingHistory.query.count(), 0)

    def test_reader_history_updates_existing_row_and_personal_sections_are_isolated(self):
        story = self._make_post(
            "Reader history story",
            "Opening this published article records the latest read time.",
            Post.STATUS_PUBLISHED,
        )
        private_story = self._make_post(
            "Another reader's story",
            "This belongs only in the other Reader's personal area.",
            Post.STATUS_PUBLISHED,
        )
        with self.app.app_context():
            reader = Reader.query.filter_by(email="feed-reader@example.com").one()
            other_reader = Reader.query.filter_by(
                email="other-reader@example.com",
            ).one()
            story_post = db.session.get(Post, story)
            private_post = db.session.get(Post, private_story)
            own_comment = Comment(
                post=story_post,
                reader=reader,
                content="My private comment listing.",
                approved=True,
            )
            other_comment = Comment(
                post=private_post,
                reader=other_reader,
                content="Another reader's private comment listing.",
                approved=False,
            )
            db.session.add_all([
                Bookmark(reader=reader, post=story_post),
                Bookmark(reader=other_reader, post=private_post),
                ReadingHistory(
                    reader=reader,
                    post=story_post,
                    read_at=datetime(2000, 1, 1),
                ),
                ReadingHistory(reader=other_reader, post=private_post),
                own_comment,
                other_comment,
            ])
            db.session.commit()

        self._login("feed-reader@example.com", "feed-reader-password", "reader")
        for _ in range(2):
            response = self.client.get(f"/posts/{story}")
            self.assertEqual(response.status_code, 200)
        dashboard = self.client.get("/reader")
        self.assertIn(b"Reader history story", dashboard.data)
        self.assertIn(b"My private comment listing.", dashboard.data)
        self.assertNotIn(b"Another reader's story", dashboard.data)
        self.assertNotIn(b"Another reader's private comment listing.", dashboard.data)
        self.assertIn(b"Approved", dashboard.data)

        with self.app.app_context():
            reader_id = Reader.query.filter_by(
                email="feed-reader@example.com",
            ).one().id
            self.assertEqual(
                ReadingHistory.query.filter_by(
                    reader_id=reader_id,
                    post_id=story,
                ).count(),
                1,
            )
            self.assertGreater(
                ReadingHistory.query.filter_by(
                    reader_id=reader_id,
                    post_id=story,
                ).one().read_at,
                datetime(2000, 1, 1),
            )

    def test_author_cannot_use_reader_area_or_bookmark_actions(self):
        post_id = self._make_post(
            "Reader-only bookmark",
            "Only Readers can bookmark this story.",
            Post.STATUS_PUBLISHED,
        )
        self._login("feed-author@example.com", "feed-author-password", "author")
        self.assertEqual(self.client.get("/reader").status_code, 403)
        token = self._csrf_token(f"/posts/{post_id}")
        response = self.client.post(
            f"/posts/{post_id}/bookmark",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(Bookmark.query.count(), 0)
            self.assertEqual(ReadingHistory.query.count(), 0)

    def test_reader_can_delete_only_their_own_comments(self):
        first_post_id = self._make_post(
            "Own comment article",
            "This is the current Reader's article.",
            Post.STATUS_PUBLISHED,
        )
        second_post_id = self._make_post(
            "Other comment article",
            "This comment belongs to another Reader.",
            Post.STATUS_PUBLISHED,
        )
        with self.app.app_context():
            own_post = db.session.get(Post, first_post_id)
            other_post = db.session.get(Post, second_post_id)
            reader = Reader.query.filter_by(
                email="feed-reader@example.com",
            ).one()
            other_reader = Reader.query.filter_by(
                email="other-reader@example.com",
            ).one()
            own_comment = Comment(
                post=own_post,
                reader=reader,
                content="My comment to delete.",
                approved=True,
            )
            other_comment = Comment(
                post=other_post,
                reader=other_reader,
                content="Another Reader's protected comment.",
                approved=True,
            )
            db.session.add_all([own_comment, other_comment])
            db.session.commit()
            own_comment_id = own_comment.id
            other_comment_id = other_comment.id

        self._login("feed-reader@example.com", "feed-reader-password", "reader")
        dashboard = self.client.get("/reader")
        self.assertIn(b"Delete comment", dashboard.data)
        token = self._csrf_token("/reader")
        response = self.client.post(
            f"/reader/comments/{own_comment_id}/delete",
            data={"_csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your comment has been deleted.", response.data)
        self.assertNotIn(b"My comment to delete.", response.data)

        token = self._csrf_token("/reader")
        response = self.client.post(
            f"/reader/comments/{other_comment_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Comment, own_comment_id))
            self.assertIsNotNone(db.session.get(Comment, other_comment_id))

    def test_author_cannot_delete_reader_comments(self):
        post_id = self._make_post(
            "Comment deletion permissions",
            "Only the owning Reader can delete their comment.",
            Post.STATUS_PUBLISHED,
        )
        with self.app.app_context():
            comment = Comment(
                post=db.session.get(Post, post_id),
                reader=Reader.query.filter_by(
                    email="feed-reader@example.com",
                ).one(),
                content="Reader-owned comment.",
                approved=True,
            )
            db.session.add(comment)
            db.session.commit()
            comment_id = comment.id

        self._login("feed-author@example.com", "feed-author-password", "author")
        token = self._csrf_token("/")
        response = self.client.post(
            f"/reader/comments/{comment_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Comment, comment_id))


if __name__ == "__main__":
    unittest.main()
