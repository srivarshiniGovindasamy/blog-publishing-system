"""Database models for the blog publishing system."""

from datetime import datetime
from math import ceil

from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin
from sqlalchemy import CheckConstraint

from extensions import db


post_categories = db.Table(
    "post_categories",
    db.Column(
        "post_id",
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "category_id",
        db.Integer,
        db.ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

post_tags = db.Table(
    "post_tags",
    db.Column(
        "post_id",
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tag_id",
        db.Integer,
        db.ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(db.Model, UserMixin):
    """Common user data; role-specific classes share the users table."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'author', 'reader')",
            name="ck_users_role",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    __mapper_args__ = {
        "polymorphic_on": role,
        # Concrete user rows can only be created through Admin, Author or Reader.
        "polymorphic_identity": "user",
    }

    def set_password(self, password):
        """Store a one-way password hash, never the submitted password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Return whether a password matches this account's stored hash."""
        return check_password_hash(self.password_hash, password)


class Admin(User):
    """The controlled administrator account type."""

    __mapper_args__ = {"polymorphic_identity": "admin"}


class Author(User):
    """A user who can access the author area."""

    __mapper_args__ = {"polymorphic_identity": "author"}
    posts = db.relationship(
        "Post",
        back_populates="author",
        cascade="all, delete-orphan",
    )


class Reader(User):
    """A user who can access the reader area."""

    __mapper_args__ = {"polymorphic_identity": "reader"}
    comments = db.relationship("Comment", back_populates="reader")
    bookmarks = db.relationship(
        "Bookmark",
        back_populates="reader",
        cascade="all, delete-orphan",
    )
    reading_history = db.relationship(
        "ReadingHistory",
        back_populates="reader",
        cascade="all, delete-orphan",
    )


class Post(db.Model):
    """A draft-first post owned by exactly one author."""

    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_posts_status",
        ),
    )

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_DRAFT,
        server_default=STATUS_DRAFT,
    )
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
    author_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    author = db.relationship("Author", back_populates="posts")
    categories = db.relationship(
        "Category",
        secondary=post_categories,
        back_populates="posts",
    )
    tags = db.relationship(
        "Tag",
        secondary=post_tags,
        back_populates="posts",
    )
    revisions = db.relationship(
        "Revision",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="Revision.revision_number.desc()",
        passive_deletes=True,
    )
    comments = db.relationship("Comment", back_populates="post")
    bookmarks = db.relationship(
        "Bookmark",
        back_populates="post",
        cascade="all, delete-orphan",
    )
    reading_history = db.relationship(
        "ReadingHistory",
        back_populates="post",
        cascade="all, delete-orphan",
    )

    @property
    def reading_time_minutes(self):
        """Estimate reading time at 200 words per minute, with a one-minute minimum."""
        return max(1, ceil(len(self.content.split()) / 200))

    def publish(self):
        """Transition a valid draft to published; return False if disallowed."""
        if (
            self.status != self.STATUS_DRAFT
            or not self.title
            or not self.title.strip()
            or not self.content
            or not self.content.strip()
        ):
            return False
        self.status = self.STATUS_PUBLISHED
        self.updated_at = datetime.utcnow()
        return True

    def archive(self):
        """Transition a published post to archived; return False if disallowed."""
        if self.status != self.STATUS_PUBLISHED:
            return False
        self.status = self.STATUS_ARCHIVED
        self.updated_at = datetime.utcnow()
        return True


class Revision(db.Model):
    """Immutable full-content snapshot owned by one Post."""

    __tablename__ = "revisions"
    __table_args__ = (
        db.UniqueConstraint(
            "post_id",
            "revision_number",
            name="uq_revisions_post_revision_number",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    post = db.relationship("Post", back_populates="revisions")


class Comment(db.Model):
    """A reader-authored comment associated with a published post."""

    __tablename__ = "comments"

    MAX_CONTENT_LENGTH = 2000

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id"),
        nullable=False,
        index=True,
    )
    reader_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    content = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    moderation_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    post = db.relationship("Post", back_populates="comments")
    reader = db.relationship("Reader", back_populates="comments")


class Bookmark(db.Model):
    """A Reader's saved reference to a post."""

    __tablename__ = "bookmarks"
    __table_args__ = (
        db.UniqueConstraint(
            "reader_id",
            "post_id",
            name="uq_bookmarks_reader_post",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    reader_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    reader = db.relationship("Reader", back_populates="bookmarks")
    post = db.relationship("Post", back_populates="bookmarks")


class ReadingHistory(db.Model):
    """The latest time a Reader opened a given post."""

    __tablename__ = "reading_history"
    __table_args__ = (
        db.UniqueConstraint(
            "reader_id",
            "post_id",
            name="uq_reading_history_reader_post",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    reader_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    reader = db.relationship("Reader", back_populates="reading_history")
    post = db.relationship("Post", back_populates="reading_history")


class Category(db.Model):
    """A reusable category associated with one or more posts."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    posts = db.relationship(
        "Post",
        secondary=post_categories,
        back_populates="categories",
    )


class Tag(db.Model):
    """A reusable tag associated with one or more posts."""

    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    posts = db.relationship(
        "Post",
        secondary=post_tags,
        back_populates="tags",
    )
