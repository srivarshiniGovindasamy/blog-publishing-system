"""Chain of Responsibility moderation behavior and integration tests."""

import re
import unittest

from app import create_app, db
from models import Author, Comment, Post, Reader
from moderation.abusive_language_filter import AbusiveLanguageFilter
from moderation.chain import create_moderation_chain
from moderation.constructive_feedback_filter import ConstructiveFeedbackFilter
from moderation.handler import CommentModerationHandler, ModerationResult
from moderation.personal_attack_filter import PersonalAttackFilter
from moderation.spam_filter import SpamFilter


class ModerationChainTests(unittest.TestCase):
    def test_default_chain_order_and_normal_comment_approval(self):
        chain = create_moderation_chain()
        self.assertIsInstance(chain, PersonalAttackFilter)
        abusive_filter = chain._next_handler
        self.assertIsInstance(abusive_filter, AbusiveLanguageFilter)
        spam_filter = abusive_filter._next_handler
        self.assertIsInstance(spam_filter, SpamFilter)
        self.assertIsInstance(spam_filter._next_handler, ConstructiveFeedbackFilter)

        result = chain.handle("This is a great article!")
        self.assertEqual(
            result,
            ModerationResult(approved=True, reason="Comment approved."),
        )

    def test_abusive_language_stops_chain_before_spam_filter(self):
        class TrackingSpamFilter(SpamFilter):
            called = False

            def reject_reason(self, content):
                self.called = True
                return super().reject_reason(content)

        personal_attack_filter = PersonalAttackFilter()
        abusive_filter = AbusiveLanguageFilter()
        spam_filter = TrackingSpamFilter()
        personal_attack_filter.set_next(abusive_filter).set_next(spam_filter)

        result = personal_attack_filter.handle("This is a stupid article.")

        self.assertFalse(result.approved)
        self.assertEqual(
            result.reason,
            "Inappropriate or offensive language detected.",
        )
        self.assertFalse(spam_filter.called)
        self.assertEqual(
            create_moderation_chain().handle("The author is useless.").reason,
            PersonalAttackFilter.REASON,
        )
        self.assertEqual(
            create_moderation_chain().handle("This is a useless article.").reason,
            AbusiveLanguageFilter.REASON,
        )

    def test_personal_attacks_are_rejected_but_constructive_criticism_is_approved(self):
        chain = create_moderation_chain()
        expected_reason = (
            "Personal attacks are not allowed. Please provide respectful, "
            "constructive feedback about the content."
        )
        result = chain.handle("You don't know anything about programming.")
        self.assertFalse(result.approved)
        self.assertEqual(result.reason, expected_reason)

        approved_comments = (
            "The explanation is good, but adding a practical example would make this easier to understand.",
            "I have a different opinion about this approach. I think the alternative method would be more efficient.",
            "There seems to be an error in the second example. Could you check the calculation?",
            "The explanation is confusing. Adding a diagram would help.",
            "Very useful post.",
        )
        for content in approved_comments:
            with self.subTest(content=content):
                self.assertTrue(chain.handle(content).approved)

    def test_spam_filter_rejects_excessive_urls_and_repeated_patterns(self):
        spam_filter = SpamFilter()
        self.assertEqual(
            spam_filter.handle(
                "visit https://one.example https://two.example "
                "https://three.example"
            ).reason,
            "Spam or irrelevant promotional content detected.",
        )
        self.assertEqual(
            spam_filter.handle("wow" + ("w" * 8)).reason,
            "Spam or irrelevant promotional content detected.",
        )
        self.assertEqual(
            spam_filter.handle("buy now now now").reason,
            "Spam or irrelevant promotional content detected.",
        )
        self.assertEqual(
            spam_filter.handle("Visit my website!!!").reason,
            "Spam or irrelevant promotional content detected.",
        )
        self.assertTrue(
            spam_filter.handle("Here is one useful reference: https://example.com").approved
        )

    def test_new_handler_can_be_inserted_without_modifying_existing_filters(self):
        class TrackingHandler(CommentModerationHandler):
            called = False

            def reject_reason(self, content):
                self.called = True
                return ""

        chain = create_moderation_chain()
        additional_filter = TrackingHandler()
        constructive_filter = chain._next_handler._next_handler._next_handler
        constructive_filter.set_next(additional_filter)

        result = chain.handle("A comment that passes all filters.")

        self.assertTrue(result.approved)
        self.assertTrue(additional_filter.called)


class ModeratedCommentFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "moderation-test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            author = Author(
                name="Moderation Author",
                email="moderation-author@example.com",
            )
            author.set_password("author-test-password")
            self.reader = Reader(
                name="Moderation Reader",
                email="moderation-reader@example.com",
            )
            self.reader.set_password("reader-test-password")
            db.session.add_all([author, self.reader])
            post = Post(
                title="Moderation article",
                content="A public article for testing moderation.",
                author=author,
                status=Post.STATUS_DRAFT,
            )
            db.session.add(post)
            db.session.commit()
            post.publish()
            db.session.commit()
            self.post_id = post.id
            self.reader_id = self.reader.id

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

    def _login_reader(self):
        token = self._csrf_token("/login")
        return self.client.post("/login", data={
            "_csrf_token": token,
            "email": "moderation-reader@example.com",
            "password": "reader-test-password",
            "role": "reader",
        })

    def _submit_comment(self, content):
        token = self._csrf_token(f"/posts/{self.post_id}")
        return self.client.post(
            f"/posts/{self.post_id}/comments",
            data={"_csrf_token": token, "content": content},
            follow_redirects=True,
        )

    def test_offensive_comment_is_saved_rejected_hidden_public_and_visible_to_owner(self):
        self._login_reader()
        response = self._submit_comment("This is a stupid article.")

        self.assertIn(
            b"Your comment could not be published.",
            response.data,
        )
        self.assertIn(b"Inappropriate or offensive language detected.", response.data)
        with self.app.app_context():
            comment = Comment.query.one()
            self.assertFalse(comment.approved)
            self.assertEqual(
                comment.moderation_reason,
                "Inappropriate or offensive language detected.",
            )
            self.assertEqual(comment.reader_id, self.reader_id)

        public_article = self.app.test_client().get(f"/posts/{self.post_id}")
        self.assertNotIn(b"This is a stupid article.", public_article.data)
        self.assertIn(b"Moderation article", public_article.data)

        reader_area = self.client.get("/reader")
        self.assertIn(b"This is a stupid article.", reader_area.data)
        self.assertIn(b"Rejected", reader_area.data)
        self.assertIn(
            b"Reason: Inappropriate or offensive language detected.",
            reader_area.data,
        )

    def test_approved_comment_has_friendly_message_and_approval_reason(self):
        self._login_reader()
        response = self._submit_comment("Great article! The explanation was very helpful.")
        self.assertIn(b"Your comment has been published.", response.data)
        self.assertIn(b"Great article! The explanation was very helpful.", response.data)
        with self.app.app_context():
            comment = Comment.query.one()
            self.assertTrue(comment.approved)
            self.assertEqual(comment.moderation_reason, "Comment approved.")

    def test_spam_comment_is_rejected_with_reason(self):
        self._login_reader()
        response = self._submit_comment(
            "See https://one.example https://two.example https://three.example"
        )
        self.assertIn(b"Your comment could not be published.", response.data)
        self.assertIn(
            b"Spam or irrelevant promotional content detected.",
            response.data,
        )
        with self.app.app_context():
            comment = Comment.query.one()
            self.assertFalse(comment.approved)
            self.assertEqual(
                comment.moderation_reason,
                "Spam or irrelevant promotional content detected.",
            )

    def test_personal_attack_rejection_reason_is_returned_to_reader(self):
        self._login_reader()
        response = self._submit_comment(
            "You don't know anything about programming."
        )
        self.assertIn(b"Your comment could not be published.", response.data)
        self.assertIn(
            b"Personal attacks are not allowed. Please provide respectful, "
            b"constructive feedback about the content.",
            response.data,
        )
        with self.app.app_context():
            comment = Comment.query.one()
            self.assertFalse(comment.approved)


if __name__ == "__main__":
    unittest.main()
