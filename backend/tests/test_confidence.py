"""
Confidence tests.

Blueprint §14 requires confidence to be *computed* from named factors rather
than asserted. These lock in that each factor actually moves the number, and in
the right direction — a confidence score that ignores its inputs is worse than
no score, because it looks authoritative.
"""
from datetime import datetime, timedelta, timezone
import pytest
from app.services.confidence import compute_confidence, WEIGHTS


def base(**overrides):
    kwargs = dict(
        data_updated_at=datetime.now(timezone.utc),
        p_start_in=1.0,
        p_start_out=1.0,
        variance=1.0,
        expected_gain=5.0,
        next_best_gain=1.0,
        matches_played=10,
    )
    kwargs.update(overrides)
    return compute_confidence(**kwargs)


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_confidence_is_a_percentage():
    c = base()
    assert 0 <= c.percent <= 100
    assert 0.0 <= c.total <= 1.0


def test_every_weighted_factor_is_reported():
    c = base()
    assert set(c.factors) == set(WEIGHTS)


def test_ideal_inputs_give_high_confidence():
    assert base().percent >= 85


def test_stale_data_lowers_confidence():
    fresh = base(data_updated_at=datetime.now(timezone.utc))
    stale = base(data_updated_at=datetime.now(timezone.utc) - timedelta(hours=30))
    assert stale.percent < fresh.percent
    assert stale.factors["data_freshness"] < fresh.factors["data_freshness"]


def test_stale_data_adds_a_note():
    c = base(data_updated_at=datetime.now(timezone.utc) - timedelta(hours=20))
    assert any("old" in n for n in c.notes)


def test_missing_timestamp_is_penalised_not_crashed():
    c = base(data_updated_at=None)
    assert c.factors["data_freshness"] < 0.5
    assert any("timestamp" in n for n in c.notes)


def test_naive_timestamp_is_handled():
    """A tz-naive datetime must not raise when subtracted from an aware now."""
    naive = datetime.now(timezone.utc).replace(tzinfo=None)
    c = base(data_updated_at=naive)
    assert 0 <= c.percent <= 100


def test_rotation_risk_lowers_confidence():
    nailed = base(p_start_in=1.0)
    risky = base(p_start_in=0.4)
    assert risky.percent < nailed.percent
    assert any("start probability" in n for n in risky.notes)


def test_high_variance_lowers_confidence():
    assert base(variance=8.0).percent < base(variance=0.5).percent


def test_narrow_margin_lowers_confidence():
    """A recommendation barely ahead of the alternative is fragile."""
    clear = base(expected_gain=5.0, next_best_gain=1.0)
    close = base(expected_gain=5.0, next_best_gain=4.9)
    assert close.percent < clear.percent
    assert any("close call" in n for n in close.notes)


def test_thin_sample_lowers_confidence_and_is_flagged():
    early = base(matches_played=1)
    late = base(matches_played=20)
    assert early.percent < late.percent
    assert any("gameweek" in n for n in early.notes)


def test_missing_alternative_does_not_crash():
    c = base(next_best_gain=None)
    assert 0 <= c.percent <= 100


def test_all_factors_are_bounded():
    for kwargs in (
        dict(variance=1000.0),
        dict(p_start_in=0.0),
        dict(matches_played=0),
        dict(expected_gain=-50.0, next_best_gain=50.0),
        dict(data_updated_at=datetime.now(timezone.utc) - timedelta(days=365)),
    ):
        c = base(**kwargs)
        assert all(0.0 <= v <= 1.0 for v in c.factors.values()), c.factors
        assert 0 <= c.percent <= 100


def test_worst_case_is_low_confidence():
    c = compute_confidence(
        data_updated_at=None,
        p_start_in=0.0,
        p_start_out=0.0,
        variance=20.0,
        expected_gain=0.1,
        next_best_gain=0.1,
        matches_played=0,
    )
    assert c.percent < 30


def test_as_dict_shape_is_stable():
    d = base().as_dict()
    assert set(d) == {"confidence", "factors", "weights", "notes"}
    assert isinstance(d["confidence"], int)
