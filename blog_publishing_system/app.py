"""
app.py — Flask Application Factory
====================================
Creates and configures the Flask application with SQLAlchemy, Flask-Login,
authentication routes, and the foundation home page.
"""

from flask import Flask, render_template, request
from sqlalchemy import func, or_

from extensions import db, login_manager
from services.content_quality_service import ContentQualityService
from services.taxonomy import (
    PREDEFINED_CATEGORIES,
    PREDEFINED_TAGS,
    ensure_predefined_terms,
)


def create_app(test_config=None):
    """Application factory — returns a fully configured Flask app."""

    app = Flask(__name__)

    # ── Load configuration ────────────────────────────────────────────
    from config import Config
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # ── Initialise extensions ─────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)

    # Flask-Login settings
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return db.session.get(User, user_id)

    # ── Register authentication and role-protected pages ──────────────
    from routes.auth import auth_bp, csrf_token
    app.register_blueprint(auth_bp)

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": csrf_token}

    # ── Foundation home-page route ────────────────────────────────────
    @app.route("/")
    def home():
        """Render the searchable, filtered, paginated published-post feed."""
        from models import Author, Category, Post, Tag

        ensure_predefined_terms()
        search = request.args.get("search", "").strip()
        category_name = request.args.get("category", "").strip()
        tag_name = request.args.get("tag", "").strip()
        page = max(1, request.args.get("page", 1, type=int) or 1)
        per_page = 9

        query = Post.query.filter_by(status=Post.STATUS_PUBLISHED)
        if search:
            query = query.join(Post.author).filter(or_(
                Post.title.contains(search, autoescape=True),
                Post.content.contains(search, autoescape=True),
                Author.name.contains(search, autoescape=True),
            ))

        if category_name:
            query = query.filter(Post.categories.any(
                func.lower(Category.name) == category_name.casefold()
            ))
        if tag_name:
            query = query.filter(Post.tags.any(
                func.lower(Tag.name) == tag_name.casefold()
            ))

        pagination = (
            query.order_by(Post.updated_at.desc(), Post.id.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        category_options = {
            category.name.casefold(): category
            for category in Category.query.filter(
                func.lower(Category.name).in_(
                    [name.casefold() for name in PREDEFINED_CATEGORIES]
                )
            ).all()
        }
        tag_options = {
            tag.name.casefold(): tag
            for tag in Tag.query.filter(
                func.lower(Tag.name).in_(
                    [name.casefold() for name in PREDEFINED_TAGS]
                )
            ).all()
        }
        seo_service = ContentQualityService()
        seo_analyses = {
            post.id: seo_service.execute("seo", post)
            for post in pagination.items
        }
        return render_template(
            "home.html",
            posts=pagination.items,
            pagination=pagination,
            search=search,
            category_name=category_name,
            tag_name=tag_name,
            categories=[
                (name, category_options[name.casefold()])
                for name in PREDEFINED_CATEGORIES
                if name.casefold() in category_options
            ],
            tags=[
                (name, tag_options[name.casefold()])
                for name in PREDEFINED_TAGS
                if name.casefold() in tag_options
            ],
            seo_analyses=seo_analyses,
        )

    # ── Error handlers ────────────────────────────────────────────────
    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("base.html",
                               error_code=404,
                               error_message="Page Not Found"), 404

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("base.html",
                               error_code=403,
                               error_message="Access Denied"), 403

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("base.html",
                               error_code=500,
                               error_message="Internal Server Error"), 500

    # ── Verify MySQL connection on first request ─────────────────────
    if not app.testing:
        with app.app_context():
            try:
                with db.engine.connect():
                    print("MySQL connection successful.")
            except Exception as exc:
                print(f"MySQL connection FAILED: {exc}")
                print("    Make sure XAMPP MySQL is running and the database exists.")

    return app


# ---------------------------------------------------------------------------
# Run the development server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
