"""
Structured categories for availability events.

Every event comes from FPL's own player data, read by the deterministic
parser, so a category is a reading of that text and never an inference. The
categories that need press conferences or journalists — rotation risk,
manager comments, training updates, line-ups — are not produced, because no
such source is connected; an empty category is better than a guessed one.
"""
from app.models.news import AvailabilityEvent

INJURY = "INJURY"
RETURN_FROM_INJURY = "RETURN_FROM_INJURY"
SUSPENSION = "SUSPENSION"
TRANSFER = "TRANSFER"
PRICE_CHANGE = "PRICE_CHANGE"
OTHER = "OTHER"

_INJURY_CAUSES = ("injury", "knock", "illness", "fitness")

SOURCE_LABELS = {"fpl_api": "FPL official"}


def _direction(e: AvailabilityEvent) -> str:
    before, after = e.availability_before, e.availability_after
    if before is None or after is None or before == after:
        return "neutral"
    return "positive" if after > before else "negative"


def categorise(e: AvailabilityEvent) -> dict:
    """Category, confidence and direction for one event."""
    cause = e.cause or ""
    direction = _direction(e)

    if e.event_type in ("price_change", "price_imminent"):
        category = PRICE_CHANGE
    elif e.event_type == "departed" or cause in ("transfer_out", "loan"):
        category = TRANSFER
    elif e.event_type == "returned":
        category = RETURN_FROM_INJURY
    elif cause == "suspension":
        category = SUSPENSION
    elif cause.startswith(_INJURY_CAUSES):
        category = RETURN_FROM_INJURY if direction == "positive" else INJURY
    else:
        category = OTHER

    return {
        "category": category,
        # Low when the parser could not read the text and the event was kept
        # for review; the raw text is always returned alongside.
        "confidence": "low" if e.requires_review else "high",
        "direction": direction,
        "source": e.source,
        "source_label": SOURCE_LABELS.get(e.source, e.source),
    }
