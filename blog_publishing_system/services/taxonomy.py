"""Canonical categories and tags available to authors."""

from sqlalchemy import func

from extensions import db
from models import Category, Tag


PREDEFINED_CATEGORIES = (
    "Technology",
    "Artificial Intelligence",
    "Programming",
    "Web Development",
    "Data Science",
    "Cybersecurity",
    "Cloud Computing",
    "Software Engineering",
    "Research",
    "Career & Education",
)

PREDEFINED_TAGS = (
    "Python",
    "Java",
    "JavaScript",
    "SQL",
    "Machine Learning",
    "Deep Learning",
    "Flask",
    "MySQL",
    "GitHub",
    "Algorithms",
)


def ensure_predefined_terms():
    """Add missing canonical terms without duplicating case-insensitive matches."""
    changed = False
    for model, names in (
        (Category, PREDEFINED_CATEGORIES),
        (Tag, PREDEFINED_TAGS),
    ):
        existing_names = {
            name.casefold()
            for (name,) in model.query.with_entities(model.name).filter(
                func.lower(model.name).in_(
                    [value.casefold() for value in names]
                )
            ).all()
        }
        for name in names:
            if name.casefold() not in existing_names:
                db.session.add(model(name=name))
                changed = True
    if changed:
        db.session.commit()


def canonicalize_terms(names, allowed_names):
    """Return canonical names for valid user-supplied taxonomy values."""
    lookup = {name.casefold(): name for name in allowed_names}
    canonical = []
    for name in names:
        value = lookup.get(name.strip().casefold())
        if value and value not in canonical:
            canonical.append(value)
    return canonical
