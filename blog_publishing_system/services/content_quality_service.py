"""Select and execute content-quality strategies."""

from strategies.related_posts_strategy import RelatedPostsStrategy
from strategies.seo_score_strategy import SEOScoreStrategy


class ContentQualityService:
    """Run an explicit strategy or select one by its stable service key."""

    def __init__(self, strategies=None):
        self._strategies = strategies or {
            "seo": SEOScoreStrategy(),
            "related_posts": RelatedPostsStrategy(),
        }

    def analyze(self, post, strategy, context=None):
        if isinstance(strategy, str):
            try:
                strategy = self._strategies[strategy]
            except KeyError as error:
                raise ValueError(f"Unknown content strategy: {strategy}") from error
        return strategy.analyze(post, context=context)

    def execute(self, strategy_name, post, context=None):
        """Execute a registered strategy using its service key."""
        return self.analyze(post, strategy_name, context=context)
