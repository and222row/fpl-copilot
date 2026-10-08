"""Categories attached to availability events."""
import pytest

from app.models.news import AvailabilityEvent
from app.services.news_taxonomy import categorise


def event(event_type="status_change", cause=None, before=1.0, after=0.0, review=False):
    return AvailabilityEvent(
        player_id=1, event_type=event_type, cause=cause, availability_before=before,
        availability_after=after, requires_review=review, source="fpl_api", news_text="",
    )


@pytest.mark.parametrize("e,category", [
    (event(cause="injury_hamstring"), "INJURY"),
    (event(cause="knock", before=1.0, after=0.75), "INJURY"),
    (event(cause="illness"), "INJURY"),
    (event("chance_change", cause="injury_ankle", before=0.25, after=0.75), "RETURN_FROM_INJURY"),
    (event("returned", cause=None, before=0.5, after=1.0), "RETURN_FROM_INJURY"),
    (event(cause="suspension"), "SUSPENSION"),
    (event("departed", cause="transfer_out"), "TRANSFER"),
    (event("ruled_out", cause="loan"), "TRANSFER"),
    (event("price_change", before=None, after=None), "PRICE_CHANGE"),
    (event("price_imminent", before=None, after=None), "PRICE_CHANGE"),
    (event("news_change", cause="international_duty", before=1.0, after=1.0), "OTHER"),
    (event("news_change", cause=None, before=1.0, after=1.0), "OTHER"),
])
def test_categories(e, category):
    assert categorise(e)["category"] == category


def test_direction_follows_availability():
    assert categorise(event(before=1.0, after=0.25))["direction"] == "negative"
    assert categorise(event(before=0.25, after=1.0))["direction"] == "positive"
    assert categorise(event("price_change", before=None, after=None))["direction"] == "neutral"


def test_unparsed_text_is_low_confidence():
    assert categorise(event(review=True))["confidence"] == "low"
    assert categorise(event())["confidence"] == "high"


def test_every_event_names_its_source():
    out = categorise(event())
    assert out["source"] == "fpl_api"
    assert out["source_label"] == "FPL official"


def test_no_category_needs_an_unconnected_source():
    # Rotation, manager comments, training and line-ups need press or
    # journalist sources. Until one exists, nothing may be labelled as such.
    produced = {
        categorise(event(t, c, b, a))["category"]
        for t in ("status_change", "chance_change", "returned", "departed", "ruled_out",
                  "news_change", "price_change", "price_imminent")
        for c in (None, "injury_knee", "knock", "suspension", "loan", "transfer_out",
                  "international_duty", "fitness")
        for b, a in ((1.0, 0.0), (0.0, 1.0), (None, None))
    }
    assert produced.isdisjoint({"ROTATION_RISK", "MANAGER_COMMENT", "TRAINING_UPDATE", "LINEUP"})
