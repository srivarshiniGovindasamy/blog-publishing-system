"""Comment creation and automated moderation orchestration."""

from extensions import db
from moderation.chain import create_moderation_chain
from models import Comment


def create_moderated_comment(reader, post, content):
    """Moderate, persist, and return a Reader's submitted comment."""
    comment = Comment(
        reader=reader,
        post=post,
        content=content,
        approved=False,
    )
    result = create_moderation_chain().handle(comment.content)
    comment.approved = result.approved
    comment.moderation_reason = result.reason or "Comment approved."
    db.session.add(comment)
    db.session.commit()
    return comment
