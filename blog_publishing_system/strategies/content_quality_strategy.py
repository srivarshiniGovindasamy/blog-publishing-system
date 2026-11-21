"""Common interface for independently executable content strategies."""

from abc import ABC, abstractmethod


class ContentQualityStrategy(ABC):
    """A strategy that analyzes one post and returns a result."""

    @abstractmethod
    def analyze(self, post, context=None):
        """Analyze the post, optionally using caller-provided context."""
