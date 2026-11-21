"""Factory for the default comment moderation chain."""

from flask import current_app, has_app_context

from moderation.abusive_language_filter import (
    AbusiveLanguageFilter,
    DEFAULT_ABUSIVE_TERMS,
)
from moderation.constructive_feedback_filter import ConstructiveFeedbackFilter
from moderation.personal_attack_filter import PersonalAttackFilter
from moderation.spam_filter import SpamFilter


def create_moderation_chain():
    """Build a specific-first default order without coupling the filters."""
    abusive_terms = DEFAULT_ABUSIVE_TERMS
    if has_app_context():
        abusive_terms = current_app.config.get(
            "COMMENT_ABUSIVE_TERMS",
            DEFAULT_ABUSIVE_TERMS,
        )
    personal_attack_filter = PersonalAttackFilter()
    abusive_filter = personal_attack_filter.set_next(AbusiveLanguageFilter(abusive_terms))
    spam_filter = abusive_filter.set_next(SpamFilter())
    spam_filter.set_next(ConstructiveFeedbackFilter())
    return personal_attack_filter
