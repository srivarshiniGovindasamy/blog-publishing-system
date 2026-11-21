"""Strategy and UI integration tests for content-quality analysis."""

import re
import unittest
from types import SimpleNamespace

from app import create_app, db
from models import Author, Category, Post, Tag
from services.content_quality_service import ContentQualityService
from strategies.content_quality_strategy import ContentQualityStrategy
from strategies.related_posts_strategy import RelatedPostsStrategy
from strategies.seo_score_strategy import SEOScoreStrategy


class SEOScoreStrategyTests(unittest.TestCase):
    def setUp(self):
        self.strategy = SEOScoreStrategy()

    def test_score_is_bounded_and_labels_follow_score_bands(self):
        samples = (
            SimpleNamespace(title="", content=""),
            SimpleNamespace(title="Clear title here", content="A short text."),
            SimpleNamespace(
                title="A reasonable title",
                content="This content repeats title details.\n\nAnother paragraph.",
            ),
        )
        for post in samples:
            with self.subTest(title=post.title):
                result = self.strategy.analyze(post)
                score = result["score"]
                expected_label = (
                    "Excellent" if score >= 80 else
                    "Good" if score >= 60 else
                    "Needs Improvement" if score >= 40 else
                    "Poor"
                )
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)
                self.assertEqual(result["label"], expected_label)

        self.assertEqual(
            self.strategy.analyze(SimpleNamespace(title="", content=""))["label"],
            "Poor",
        )

    def test_structured_relevant_content_scores_higher_than_empty_content(self):
        poor = self.strategy.analyze(SimpleNamespace(title="", content=""))
        good = self.strategy.analyze(SimpleNamespace(
            title="Python Functions Explained",
            content=(
                "# Python Functions\n\n"
                + "Python functions make code reusable. " * 35
                + "\n\n## Using functions\n\n"
                + "Python functions also make code easier to test. " * 35
                + "\n\n## Conclusion\n\n"
                + "These Python functions improve applications. " * 30
            ),
        ))
        self.assertGreater(good["score"], poor["score"])
        self.assertIn(good["label"], {"Good", "Excellent"})
        self.assertTrue(good["reasons"])

    def test_service_executes_registered_and_explicit_strategies(self):
        service = ContentQualityService()
        post = SimpleNamespace(
            id=1,
            title="A Useful Title",
            content="A useful content.",
            categories=[],
            tags=[],
            status=Post.STATUS_PUBLISHED,
        )

        seo_result = service.execute("seo", post)
        related_result = service.analyze(
            post,
            RelatedPostsStrategy(),
            context=[],
        )

        self.assertIn("score", seo_result)
        self.assertEqual(related_result, [])
        self.assertIsInstance(SEOScoreStrategy(), ContentQualityStrategy)
        self.assertIsInstance(RelatedPostsStrategy(), ContentQualityStrategy)
        with self.assertRaises(ValueError):
            service.execute("unknown", post)


class RelatedPostsStrategyTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "quality-test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        with self.app.app_context():
            db.create_all()
            author = Author(name="Quality Author", email="quality@example.com")
            author.set_password("quality-password")
            db.session.add(author)
            self.category = Category(name="Development")
            self.tag = Tag(name="python")
            db.session.add_all([self.category, self.tag])
            db.session.commit()
            self.current_post = self._make_post(
                author,
                "Python functions guide",
                "Learn useful Python function patterns.",
                Post.STATUS_PUBLISHED,
                categorized=True,
                tagged=True,
            )
            self.related_post = self._make_post(
                author,
                "Python functions examples",
                "Examples of function patterns and code.",
                Post.STATUS_PUBLISHED,
                categorized=True,
                tagged=True,
            )
            self.same_tag_post = self._make_post(
                author,
                "Python testing notes",
                "A guide to testing code.",
                Post.STATUS_PUBLISHED,
                tagged=True,
            )
            self.draft_post = self._make_post(
                author,
                "Python draft guide",
                "Draft content should not be recommended.",
                Post.STATUS_DRAFT,
                categorized=True,
                tagged=True,
            )
            self.archived_post = self._make_post(
                author,
                "Archived Python guide",
                "Archived content should not be recommended.",
                Post.STATUS_ARCHIVED,
                categorized=True,
                tagged=True,
            )
            db.session.commit()
            self.current_id = self.current_post.id
            self.related_id = self.related_post.id
            self.same_tag_id = self.same_tag_post.id
            self.draft_id = self.draft_post.id
            self.archived_id = self.archived_post.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _make_post(
        self,
        author,
        title,
        content,
        status,
        categorized=False,
        tagged=False,
    ):
        post = Post(
            author=author,
            title=title,
            content=content,
            status=status,
        )
        if categorized:
            post.categories.append(self.category)
        if tagged:
            post.tags.append(self.tag)
        db.session.add(post)
        return post

    def test_related_strategy_prioritizes_shared_terms_and_excludes_unpublished(self):
        with self.app.app_context():
            current_post = db.session.get(Post, self.current_id)
            results = RelatedPostsStrategy(limit=4).analyze(current_post)
            result_ids = [post.id for post in results]

            self.assertEqual(result_ids[0], self.related_id)
            self.assertIn(self.same_tag_id, result_ids)
            self.assertNotIn(self.current_id, result_ids)
            self.assertNotIn(self.draft_id, result_ids)
            self.assertNotIn(self.archived_id, result_ids)
            self.assertLessEqual(len(results), 4)

    def test_public_article_displays_seo_and_related_published_stories(self):
        with self.app.app_context():
            current_id = self.current_id
            related_title = db.session.get(Post, self.related_id).title
        client = self.app.test_client()
        response = client.get(f"/posts/{current_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SEO Score", response.data)
        self.assertIn(b"Related stories", response.data)
        self.assertIn(related_title.encode(), response.data)
        self.assertNotIn(b"Python draft guide", response.data)
        self.assertNotIn(b"Archived Python guide", response.data)


class ContentQualityAuthorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "quality-author-test-session-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            author = Author(
                name="Quality Author",
                email="quality-author@example.com",
            )
            author.set_password("quality-author-password")
            db.session.add(author)
            db.session.commit()
        token = self._csrf_token("/login")
        self.client.post("/login", data={
            "_csrf_token": token,
            "email": "quality-author@example.com",
            "password": "quality-author-password",
            "role": "author",
        })

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

    def test_author_can_see_quality_score_and_low_score_does_not_block_publish(self):
        token = self._csrf_token("/author/posts/new")
        response = self.client.post("/author/posts/new", data={
            "_csrf_token": token,
            "title": "x",
            "content": "Short content.",
            "action": "save",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            post = Post.query.one()
            post_id = post.id
        token = self._csrf_token("/author")
        response = self.client.post(
            f"/author/posts/{post_id}/publish",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Post, post_id).status,
                Post.STATUS_PUBLISHED,
            )

        dashboard = self.client.get("/author")
        self.assertIn(b"SEO Score", dashboard.data)
        edit_page = self.client.get(f"/author/posts/{post_id}/edit")
        self.assertIn(b"SEO Score", edit_page.data)


if __name__ == "__main__":
    unittest.main()
