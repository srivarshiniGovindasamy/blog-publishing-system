"""Find related published posts using shared terms and content keywords."""

import re

from strategies.content_quality_strategy import ContentQualityStrategy


class RelatedPostsStrategy(ContentQualityStrategy):
    """Rank published posts by shared categories, tags and useful keywords."""

    STOP_WORDS = {
        "about", "after", "also", "and", "are", "because", "been", "being",
        "but", "can", "could", "did", "does", "for", "from", "had", "has",
        "have", "her", "here", "his", "how", "into", "its", "not", "our",
        "out", "post", "posts", "should", "some", "than", "that", "the",
        "their", "them", "then", "there", "these", "they", "this", "those",
        "through", "under", "very", "was", "were", "what", "when", "where",
        "which", "while", "with", "would", "you", "your",
    }

    def __init__(self, limit=4):
        self.limit = max(1, limit)

    @classmethod
    def _keywords(cls, post):
        text = f"{post.title or ''} {post.content or ''}".casefold()
        return {
            word
            for word in re.findall(r"\b[\w'-]{3,}\b", text)
            if word not in cls.STOP_WORDS
        }

    def analyze(self, post, context=None):
        from models import Post

        candidates = context
        if candidates is None:
            candidates = Post.query.filter_by(
                status=Post.STATUS_PUBLISHED,
            ).filter(Post.id != post.id).all()

        current_categories = {category.id for category in post.categories}
        current_tags = {tag.id for tag in post.tags}
        current_keywords = self._keywords(post)
        ranked = []
        for candidate in candidates:
            if (
                candidate.id == post.id
                or candidate.status != Post.STATUS_PUBLISHED
            ):
                continue

            shared_categories = current_categories.intersection(
                category.id for category in candidate.categories
            )
            shared_tags = current_tags.intersection(
                tag.id for tag in candidate.tags
            )
            shared_keywords = current_keywords.intersection(
                self._keywords(candidate)
            )
            relevance = (
                5 * len(shared_categories)
                + 3 * len(shared_tags)
                + min(len(shared_keywords), 5)
            )
            if relevance == 0:
                continue
            ranked.append((
                relevance,
                candidate.updated_at,
                candidate.id,
                candidate,
            ))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in ranked[:self.limit]]
