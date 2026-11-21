"""Public search, taxonomy filtering, and pagination tests."""

import unittest

from sqlalchemy import func

from app import create_app, db
from models import Author, Category, Post, Tag
from services.taxonomy import ensure_predefined_terms


class PublicSearchTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "public-search-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            ensure_predefined_terms()
            self.author = Author(
                name="Blog Contributor",
                email="blog-author@example.com",
            )
            self.author.set_password("blog-author-password")
            self.search_author = Author(
                name="Python Contributor",
                email="python-search-author@example.com",
            )
            self.search_author.set_password("python-search-password")
            self.programming = Category.query.filter_by(name="Programming").one()
            self.data_science = Category.query.filter_by(name="Data Science").one()
            self.python = Tag.query.filter_by(name="Python").one()
            self.algorithms = Tag.query.filter_by(name="Algorithms").one()
            self.flask = Tag.query.filter_by(name="Flask").one()
            db.session.add_all([self.author, self.search_author])
            db.session.flush()
            self._add_post(
                "Python algorithms guide",
                "A guide to algorithms and Python programming.",
                [self.programming],
                [self.python, self.algorithms],
            )
            self._add_post(
                "Flask algorithms guide",
                "Python web tools for useful algorithms.",
                [self.programming],
                [self.flask, self.algorithms],
            )
            self._add_post(
                "Python data study",
                "A Python overview for researchers.",
                [self.data_science],
                [self.python],
            )
            self._add_post(
                "Literal wildcard 100%_guide",
                "Find this exact special-character phrase.",
                [self.programming],
                [self.python],
            )
            self._add_post(
                "Author search story",
                "This article matches its author's name.",
                [self.data_science],
                [self.python],
                author=self.search_author,
            )
            self._add_post(
                "Private Python draft",
                "This draft must stay out of public results.",
                [self.programming],
                [self.python, self.algorithms],
                Post.STATUS_DRAFT,
            )
            self._add_post(
                "Archived Python guide",
                "This archived story must stay out of public results.",
                [self.programming],
                [self.python, self.algorithms],
                Post.STATUS_ARCHIVED,
            )
            for index in range(11):
                self._add_post(
                    f"Page story {index:02d}",
                    "Pageable programming material.",
                    [self.programming],
                    [self.python],
                )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _add_post(
        self,
        title,
        content,
        categories,
        tags,
        status=Post.STATUS_PUBLISHED,
        author=None,
    ):
        db.session.add(Post(
            title=title,
            content=content,
            status=status,
            author=author or self.author,
            categories=categories,
            tags=tags,
        ))

    def test_public_search_checks_title_content_author_and_escapes_like_chars(self):
        response = self.client.get("/?search=algorithms")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Python algorithms guide", response.data)
        self.assertIn(b"Flask algorithms guide", response.data)
        self.assertNotIn(b"Private Python draft", response.data)
        self.assertNotIn(b"Archived Python guide", response.data)

        response = self.client.get("/?search=Python+Contributor")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Python Contributor", response.data)
        self.assertIn(b"Author search story", response.data)

        response = self.client.get("/?search=100%25_guide")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Literal wildcard 100%_guide", response.data)
        self.assertNotIn(b"Python algorithms guide", response.data)

    def test_category_and_tag_filters_use_database_relationships(self):
        category_response = self.client.get("/?category=Programming")
        self.assertEqual(category_response.status_code, 200)
        self.assertIn(b"Page story 10", category_response.data)
        self.assertNotIn(b"Python data study", category_response.data)

        tag_response = self.client.get("/?tag=Flask")
        self.assertEqual(tag_response.status_code, 200)
        self.assertIn(b"Flask algorithms guide", tag_response.data)
        self.assertNotIn(b"Python algorithms guide", tag_response.data)

    def test_search_category_and_tag_combine_and_reset_clears_state(self):
        response = self.client.get(
            "/?search=Python&category=Programming&tag=Algorithms"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Python algorithms guide", response.data)
        self.assertIn(b"Flask algorithms guide", response.data)
        self.assertNotIn(b"Python data study", response.data)
        self.assertNotIn(b"Private Python draft", response.data)

        self.assertIn(b'value="Python"', response.data)
        self.assertIn(b'value="Programming"', response.data)
        self.assertIn(b'value="Algorithms"', response.data)
        self.assertIn(b"Reset Filters", response.data)
        reset_response = self.client.get("/")
        self.assertEqual(reset_response.status_code, 200)
        self.assertIn(b"All Categories", reset_response.data)
        self.assertIn(b"All Tags", reset_response.data)

    def test_predefined_terms_are_initialized_without_case_insensitive_duplicates(self):
        with self.app.app_context():
            category = Category.query.filter_by(name="Cybersecurity").one()
            tag = Tag.query.filter_by(name="Java").one()
            db.session.delete(category)
            db.session.delete(tag)
            db.session.add_all([
                Category(name="cybersecurity"),
                Tag(name="java"),
            ])
            db.session.commit()

            ensure_predefined_terms()
            self.assertEqual(
                Category.query.filter(
                    func.lower(Category.name) == "cybersecurity"
                ).count(),
                1,
            )
            self.assertEqual(
                Tag.query.filter(func.lower(Tag.name) == "java").count(),
                1,
            )

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertRegex(
            page,
            r'<option value="Cybersecurity"[\s\S]*?>\s*Cybersecurity\s*</option>',
        )
        self.assertRegex(
            page,
            r'<option value="Java"[\s\S]*?>\s*Java\s*</option>',
        )

    def test_server_pagination_preserves_filters_and_handles_empty_pages(self):
        page_one = self.client.get(
            "/?search=Page&category=Programming&tag=Python"
        )
        self.assertEqual(page_one.status_code, 200)
        self.assertIn(b"Page story 10", page_one.data)
        self.assertIn(b"Page story 02", page_one.data)
        self.assertNotIn(b"Page story 01", page_one.data)
        self.assertIn(b"Next", page_one.data)

        page_two = self.client.get(
            "/?search=Page&category=Programming&tag=Python&page=2"
        )
        self.assertEqual(page_two.status_code, 200)
        self.assertIn(b"Page story 01", page_two.data)
        self.assertIn(b"Page story 00", page_two.data)
        self.assertNotIn(b"Page story 02", page_two.data)
        self.assertIn(b"search=Page", page_two.data)
        self.assertIn(b"category=Programming", page_two.data)
        self.assertIn(b"tag=Python", page_two.data)

        empty_page = self.client.get(
            "/?search=Page&category=Programming&tag=Python&page=99"
        )
        self.assertEqual(empty_page.status_code, 200)
        self.assertIn(b"No posts found for your search.", empty_page.data)


if __name__ == "__main__":
    unittest.main()
