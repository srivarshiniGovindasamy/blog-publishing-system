"""Registration, login, logout, and role-specific placeholder areas."""

import hmac
import re
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    Admin,
    Author,
    Bookmark,
    Category,
    Comment,
    Post,
    Reader,
    ReadingHistory,
    Revision,
    Tag,
    User,
)
from services.comment_service import create_moderated_comment
from services.content_quality_service import ContentQualityService
from services.taxonomy import (
    PREDEFINED_CATEGORIES,
    PREDEFINED_TAGS,
    canonicalize_terms,
    ensure_predefined_terms,
)


auth_bp = Blueprint("auth", __name__)
content_quality_service = ContentQualityService()
REGISTERABLE_ROLES = {"author": Author, "reader": Reader}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_PASSWORD_LENGTH = 128


def csrf_token():
    """Return a session-bound token for authentication forms."""
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@auth_bp.before_request
def protect_auth_forms():
    if request.method == "POST":
        expected = session.get("_csrf_token", "")
        submitted = request.form.get("_csrf_token", "")
        if not expected or not hmac.compare_digest(expected, submitted):
            abort(400, description="Invalid or missing form security token.")


def role_required(*allowed_roles):
    """Restrict a view to authenticated users with one of the given roles."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def dashboard_url(user):
    """Return the dashboard route for a user's persisted role."""
    endpoints = {
        "admin": "auth.admin_dashboard",
        "author": "auth.author_dashboard",
        "reader": "auth.reader_dashboard",
    }
    return url_for(endpoints[user.role])


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(dashboard_url(current_user))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        role = request.form.get("role", "").strip().lower()

        if not name or len(name) > 120:
            flash("Enter a name of 1 to 120 characters.", "error")
        elif not EMAIL_PATTERN.fullmatch(email) or len(email) > 255:
            flash("Enter a valid email address.", "error")
        elif role not in REGISTERABLE_ROLES:
            flash("Choose either Author or Reader to register.", "error")
        elif len(password) < 8 or len(password) > MAX_PASSWORD_LENGTH:
            flash("Use a password between 8 and 128 characters.", "error")
        elif password != confirmation:
            flash("The passwords do not match.", "error")
        else:
            user = REGISTERABLE_ROLES[role](name=name, email=email)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("An account with that email address already exists.", "error")
            else:
                flash("Your account has been created. You can now log in.", "success")
                return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(dashboard_url(current_user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        selected_role = request.form.get("role", "").strip().lower()

        user = User.query.filter_by(email=email).first()
        if selected_role not in {"admin", "author", "reader"}:
            flash("Choose Admin, Author, or Reader.", "error")
        elif user is None or not user.check_password(password):
            flash("The email or password is incorrect.", "error")
        elif user.role != selected_role:
            flash(
                "The selected role does not match this account. "
                "Choose the role used during registration.",
                "error",
            )
        else:
            login_user(user, remember=False, fresh=True)
            flash("You are now signed in.", "success")
            return redirect(dashboard_url(user))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/author")
@role_required("author")
def author_dashboard():
    posts = (
        Post.query.filter_by(author_id=current_user.id)
        .order_by(Post.updated_at.desc(), Post.id.desc())
        .all()
    )
    counts = {
        status: sum(post.status == status for post in posts)
        for status in (
            Post.STATUS_DRAFT,
            Post.STATUS_PUBLISHED,
            Post.STATUS_ARCHIVED,
        )
    }
    seo_analyses = {
        post.id: content_quality_service.execute("seo", post)
        for post in posts
    }
    return render_template(
        "auth/author_dashboard.html",
        posts=posts,
        counts=counts,
        seo_analyses=seo_analyses,
    )


def _names_from_form(field_name):
    """Read comma-separated or repeated values and preserve first occurrence."""
    names = []
    seen = set()
    for value in request.form.getlist(field_name):
        for raw_name in value.split(","):
            name = raw_name.strip()
            normalized = name.casefold()
            if name and normalized not in seen:
                names.append(name)
                seen.add(normalized)
    return names


def _find_or_create_term(model, name):
    term = model.query.filter(func.lower(model.name) == name.lower()).first()
    if term is None:
        term = model(name=name)
        db.session.add(term)
    return term


def _next_revision_number(post):
    if post.id is None:
        return 1
    highest_number = (
        db.session.query(func.max(Revision.revision_number))
        .filter_by(post_id=post.id)
        .scalar()
    )
    return (highest_number or 0) + 1


def _snapshot_post(post):
    post.revisions.append(
        Revision(
            revision_number=_next_revision_number(post),
            content=post.content,
        )
    )


def _save_post(post=None, publish=False):
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    raw_categories = _names_from_form("categories")
    raw_tags = _names_from_form("tags")
    categories = canonicalize_terms(raw_categories, PREDEFINED_CATEGORIES)
    tags = canonicalize_terms(raw_tags, PREDEFINED_TAGS)

    if not title or len(title) > 200:
        flash("Enter a title of 1 to 200 characters.", "error")
        return False
    if not content:
        flash("Post content cannot be empty.", "error")
        return False
    if any(len(name) > 100 for name in categories):
        flash("Category names must be 100 characters or fewer.", "error")
        return False
    if any(len(name) > 50 for name in tags):
        flash("Tag names must be 50 characters or fewer.", "error")
        return False
    if len(categories) != len(raw_categories):
        flash("Choose categories from the predefined list.", "error")
        return False
    if len(tags) != len(raw_tags):
        flash("Choose tags from the predefined list.", "error")
        return False

    if post is None:
        post = Post(author=current_user)
    else:
        existing_category_names = {
            name.casefold() for name in PREDEFINED_CATEGORIES
        }
        existing_tag_names = {name.casefold() for name in PREDEFINED_TAGS}
        categories.extend(
            category.name
            for category in post.categories
            if category.name.casefold() not in existing_category_names
        )
        tags.extend(
            tag.name
            for tag in post.tags
            if tag.name.casefold() not in existing_tag_names
        )
    post.title = title
    post.content = content
    db.session.add(post)
    post.categories = [_find_or_create_term(Category, name) for name in categories]
    post.tags = [_find_or_create_term(Tag, name) for name in tags]
    if publish and not post.publish():
        flash("Only a valid draft can be published.", "error")
        db.session.rollback()
        return False
    _snapshot_post(post)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise
    return True


def _render_post_form(post=None):
    ensure_predefined_terms()
    category_map = {
        category.name.casefold(): category for category in Category.query.all()
    }
    tag_map = {tag.name.casefold(): tag for tag in Tag.query.all()}
    selected_categories = (
        _names_from_form("categories")
        if request.method == "POST"
        else [category.name for category in post.categories] if post else []
    )
    selected_tags = (
        _names_from_form("tags")
        if request.method == "POST"
        else [tag.name for tag in post.tags] if post else []
    )
    category_names = {name.casefold() for name in PREDEFINED_CATEGORIES}
    tag_names = {name.casefold() for name in PREDEFINED_TAGS}
    selected_categories = canonicalize_terms(
        selected_categories,
        PREDEFINED_CATEGORIES,
    ) + [
        name for name in selected_categories
        if name.casefold() not in category_names
    ]
    selected_tags = canonicalize_terms(selected_tags, PREDEFINED_TAGS) + [
        name for name in selected_tags if name.casefold() not in tag_names
    ]
    return render_template(
        "auth/post_form.html",
        post=post,
        categories=[
            (name, category_map[name.casefold()])
            for name in PREDEFINED_CATEGORIES
            if name.casefold() in category_map
        ],
        tags=[
            (name, tag_map[name.casefold()])
            for name in PREDEFINED_TAGS
            if name.casefold() in tag_map
        ],
        selected_categories=selected_categories,
        selected_tags=selected_tags,
        revisions=post.revisions if post else [],
        seo_analysis=(
            content_quality_service.execute("seo", post)
            if post else None
        ),
    )


@auth_bp.route("/author/posts/new", methods=["GET", "POST"])
@role_required("author")
def create_post():
    if request.method == "POST":
        publish = request.form.get("action") == "publish"
        if _save_post(publish=publish):
            flash(
                "Your post is now published."
                if publish else "Your post was saved as a draft.",
                "success",
            )
            return redirect(url_for("auth.author_dashboard"))
        return _render_post_form()
    return _render_post_form()


@auth_bp.route("/author/posts/<int:post_id>/edit", methods=["GET", "POST"])
@role_required("author")
def edit_post(post_id):
    post = Post.query.filter_by(id=post_id, author_id=current_user.id).first_or_404()
    if post.status == Post.STATUS_ARCHIVED:
        return redirect(url_for("auth.author_post", post_id=post.id))

    if request.method == "POST":
        publish = request.form.get("action") == "publish"
        if _save_post(post, publish=publish):
            flash(
                "Your post is now published."
                if publish else "Your changes were saved.",
                "success",
            )
            return redirect(url_for("auth.author_dashboard"))
        return _render_post_form(post)
    return _render_post_form(post)


@auth_bp.route("/author/posts/<int:post_id>")
@role_required("author")
def author_post(post_id):
    post = Post.query.filter_by(id=post_id, author_id=current_user.id).first_or_404()
    return render_template(
        "auth/author_post.html",
        post=post,
        revisions=post.revisions,
    )


@auth_bp.route("/author/posts/<int:post_id>/revisions/<int:revision_id>/rollback", methods=["POST"])
@role_required("author")
def rollback_revision(post_id, revision_id):
    post = Post.query.filter_by(id=post_id, author_id=current_user.id).first_or_404()
    revision = Revision.query.filter_by(
        id=revision_id,
        post_id=post.id,
    ).first_or_404()

    post.content = revision.content
    post.updated_at = datetime.utcnow()
    _snapshot_post(post)
    db.session.commit()
    flash(
        f"Your post was restored from Revision {revision.revision_number}. "
        "The rollback has been saved as a new revision.",
        "success",
    )
    return redirect(url_for("auth.edit_post", post_id=post.id) + "#revision-history")


@auth_bp.route("/author/posts/<int:post_id>/publish", methods=["POST"])
@role_required("author")
def publish_post(post_id):
    post = Post.query.filter_by(id=post_id, author_id=current_user.id).first_or_404()
    if not post.publish():
        flash("Only a draft with a title and content can be published.", "error")
    else:
        db.session.commit()
        flash("Your post is now published.", "success")
    return redirect(url_for("auth.author_dashboard"))


@auth_bp.route("/author/posts/<int:post_id>/archive", methods=["POST"])
@role_required("author")
def archive_post(post_id):
    post = Post.query.filter_by(id=post_id, author_id=current_user.id).first_or_404()
    if not post.archive():
        flash("Only a published post can be archived.", "error")
    else:
        db.session.commit()
        flash("Your post has been archived.", "success")
    return redirect(url_for("auth.author_dashboard"))


@auth_bp.route("/posts/<int:post_id>")
def public_post(post_id):
    post = Post.query.filter_by(
        id=post_id,
        status=Post.STATUS_PUBLISHED,
    ).first_or_404()
    if current_user.is_authenticated and current_user.role == "reader":
        history = ReadingHistory.query.filter_by(
            reader_id=current_user.id,
            post_id=post.id,
        ).first()
        if history is None:
            history = ReadingHistory(reader=current_user, post=post)
            db.session.add(history)
        else:
            history.read_at = datetime.utcnow()
        db.session.commit()

    seo_analysis = content_quality_service.execute("seo", post)
    related_posts = content_quality_service.execute("related_posts", post)
    comments = (
        Comment.query.filter_by(post_id=post.id, approved=True)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .all()
    )
    is_bookmarked = False
    if current_user.is_authenticated and current_user.role == "reader":
        is_bookmarked = Bookmark.query.filter_by(
            reader_id=current_user.id,
            post_id=post.id,
        ).first() is not None
    return render_template(
        "auth/public_post.html",
        post=post,
        comments=comments,
        is_bookmarked=is_bookmarked,
        seo_analysis=seo_analysis,
        related_posts=related_posts,
    )


@auth_bp.route("/posts/<int:post_id>/bookmark", methods=["POST"])
def add_bookmark(post_id):
    post = Post.query.filter_by(
        id=post_id,
        status=Post.STATUS_PUBLISHED,
    ).first_or_404()
    if not current_user.is_authenticated:
        flash("Please log in as a Reader to bookmark stories.", "info")
        return redirect(url_for("auth.login"))
    if current_user.role != "reader":
        abort(403)

    bookmark = Bookmark.query.filter_by(
        reader_id=current_user.id,
        post_id=post.id,
    ).first()
    if bookmark is None:
        db.session.add(Bookmark(reader=current_user, post=post))
        db.session.commit()
        flash("Story added to your bookmarks.", "success")
    else:
        flash("This story is already in your bookmarks.", "info")
    return redirect(url_for("auth.public_post", post_id=post.id))


@auth_bp.route("/posts/<int:post_id>/bookmark/remove", methods=["POST"])
@role_required("reader")
def remove_bookmark(post_id):
    bookmark = Bookmark.query.filter_by(
        reader_id=current_user.id,
        post_id=post_id,
    ).first_or_404()
    is_published = bookmark.post.status == Post.STATUS_PUBLISHED
    db.session.delete(bookmark)
    db.session.commit()
    flash("Story removed from your bookmarks.", "success")
    if is_published:
        return redirect(url_for("auth.public_post", post_id=post_id))
    return redirect(url_for("auth.reader_dashboard"))


@auth_bp.route("/posts/<int:post_id>/comments", methods=["POST"])
def add_comment(post_id):
    post = Post.query.filter_by(
        id=post_id,
        status=Post.STATUS_PUBLISHED,
    ).first_or_404()

    if not current_user.is_authenticated:
        flash("Please log in as a Reader to comment.", "info")
        return redirect(url_for("auth.login"))
    if current_user.role != "reader":
        abort(403)

    content = request.form.get("content", "").strip()
    if not content:
        flash("Write a comment before submitting.", "error")
    elif len(content) > Comment.MAX_CONTENT_LENGTH:
        flash(
            f"Comments must be {Comment.MAX_CONTENT_LENGTH} characters or fewer.",
            "error",
        )
    else:
        comment = create_moderated_comment(current_user, post, content)
        if comment.approved:
            flash("Your comment has been published.", "success")
        else:
            flash(
                "Your comment could not be published.",
                "error",
            )
            flash(comment.moderation_reason, "info")
    return redirect(url_for("auth.public_post", post_id=post.id) + "#comments")


@auth_bp.route("/reader/comments/<int:comment_id>/delete", methods=["POST"])
@role_required("reader")
def delete_reader_comment(comment_id):
    comment = Comment.query.filter_by(
        id=comment_id,
        reader_id=current_user.id,
    ).first_or_404()
    db.session.delete(comment)
    db.session.commit()
    flash("Your comment has been deleted.", "success")
    return redirect(url_for("auth.reader_dashboard") + "#my-comments")


@auth_bp.route("/reader")
@role_required("reader")
def reader_dashboard():
    bookmarks = (
        Bookmark.query.filter_by(reader_id=current_user.id)
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .all()
    )
    reading_history = (
        ReadingHistory.query.filter_by(reader_id=current_user.id)
        .order_by(ReadingHistory.read_at.desc(), ReadingHistory.id.desc())
        .all()
    )
    comments = (
        Comment.query.filter_by(reader_id=current_user.id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .all()
    )
    return render_template(
        "auth/reader_dashboard.html",
        bookmarks=bookmarks,
        reading_history=reading_history,
        comments=comments,
    )


@auth_bp.route("/admin")
@auth_bp.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    user_counts = {
        role: User.query.filter_by(role=role).count()
        for role in ("admin", "author", "reader")
    }
    user_counts["total"] = sum(user_counts.values())
    return render_template("auth/admin_dashboard.html", user_counts=user_counts)


@auth_bp.route("/admin/users")
@role_required("admin")
def admin_users():
    users = User.query.order_by(User.name, User.id).all()
    return render_template("auth/admin_users.html", users=users)


@auth_bp.route("/admin/users/<int:user_id>/role", methods=["POST"])
@role_required("admin")
def change_user_role(user_id):
    user = User.query.filter_by(id=user_id).first_or_404()
    requested_role = request.form.get("role", "").strip().lower()
    if user.role == "admin":
        flash("This administrator account is protected.", "error")
        return redirect(url_for("auth.admin_users"))
    if requested_role not in {"author", "reader"}:
        flash("Choose either Author or Reader.", "error")
        return redirect(url_for("auth.admin_users"))
    if requested_role == user.role:
        flash("The user already has that role.", "info")
        return redirect(url_for("auth.admin_users"))

    has_posts = Post.query.filter_by(author_id=user.id).first() is not None
    has_reader_activity = any((
        Comment.query.filter_by(reader_id=user.id).first() is not None,
        Bookmark.query.filter_by(reader_id=user.id).first() is not None,
        ReadingHistory.query.filter_by(reader_id=user.id).first() is not None,
    ))
    if (user.role == "author" and has_posts) or (
        user.role == "reader" and has_reader_activity
    ):
        flash(
            "This role cannot be changed while the account has associated "
            "posts or Reader activity.",
            "error",
        )
        return redirect(url_for("auth.admin_users"))

    db.session.query(User).filter_by(id=user.id).update(
        {User.role: requested_role},
        synchronize_session=False,
    )
    db.session.commit()
    db.session.expunge(user)
    db.session.expire_all()
    flash("User role updated successfully.", "success")
    return redirect(url_for("auth.admin_users"))


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(user_id):
    user = User.query.filter_by(id=user_id).first_or_404()
    if user.role == "admin":
        flash("This administrator account is protected.", "error")
        return redirect(url_for("auth.admin_users"))

    has_posts = Post.query.filter_by(author_id=user.id).first() is not None
    has_comments = Comment.query.filter_by(reader_id=user.id).first() is not None
    has_bookmarks = Bookmark.query.filter_by(reader_id=user.id).first() is not None
    has_reading_history = (
        ReadingHistory.query.filter_by(reader_id=user.id).first() is not None
    )
    if has_posts or has_comments or has_bookmarks or has_reading_history:
        flash(
            "This account cannot be deleted because it has associated posts "
            "or Reader activity.",
            "error",
        )
        return redirect(url_for("auth.admin_users"))

    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully.", "success")
    return redirect(url_for("auth.admin_users"))
