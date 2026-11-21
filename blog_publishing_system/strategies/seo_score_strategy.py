"""Deterministic, explainable SEO score calculation."""

import re
from html import unescape

from strategies.content_quality_strategy import ContentQualityStrategy


class SEOScoreStrategy(ContentQualityStrategy):
    """Score post titles, content depth, structure and title relevance."""

    SCORE_BANDS = (
        (80, "Excellent"),
        (60, "Good"),
        (40, "Needs Improvement"),
        (0, "Poor"),
    )

    def analyze(self, post, context=None):
        title = (post.title or "").strip()
        raw_content = post.content or ""
        content = unescape(re.sub(r"<[^>]+>", " ", raw_content))
        words = re.findall(r"\b[\w'-]+\b", content.casefold())
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", raw_content.strip())
            if paragraph.strip()
        ]
        reasons = []
        score = 0

        if title:
            score += 10
            reasons.append("A title is present.")
        else:
            reasons.append("Add a clear title.")

        title_length = len(title)
        if 15 <= title_length <= 70:
            score += 10
            reasons.append("Title length is suitable for a search result.")
        elif title:
            reasons.append("Aim for a title between 15 and 70 characters.")

        word_count = len(words)
        if word_count >= 300:
            score += 25
            reasons.append("Content has good depth.")
        elif word_count >= 150:
            score += 18
            reasons.append("Content length is reasonable.")
        elif word_count >= 75:
            score += 10
            reasons.append("Consider adding more useful detail.")
        else:
            reasons.append("Add more helpful content to improve depth.")

        if len(paragraphs) >= 3:
            score += 20
            reasons.append("Content is organized into readable paragraphs.")
        elif len(paragraphs) >= 2:
            score += 12
            reasons.append("Consider splitting content into more paragraphs.")
        else:
            reasons.append("Break the content into readable paragraphs.")

        if re.search(r"(?m)^\s{0,3}#{1,6}\s+\S|<h[1-6]\b", raw_content, re.IGNORECASE):
            score += 15
            reasons.append("Headings help readers scan the content.")
        elif word_count >= 200:
            reasons.append("Consider adding headings to longer content.")
        else:
            score += 8
            reasons.append("Headings are optional for a short post.")

        title_keywords = {
            word
            for word in re.findall(r"\b[\w'-]+\b", title.casefold())
            if len(word) > 2
        }
        matched_keywords = title_keywords.intersection(words)
        if title_keywords and matched_keywords:
            score += 20
            reasons.append("The content includes important words from the title.")
        elif not title_keywords:
            score += 10
            reasons.append("Add descriptive words to the title for clearer relevance.")
        else:
            reasons.append("Use the main title terms naturally in the content.")

        score = max(0, min(100, score))
        label = next(
            label
            for threshold, label in self.SCORE_BANDS
            if score >= threshold
        )
        return {
            "score": score,
            "label": label,
            "reasons": reasons,
        }
