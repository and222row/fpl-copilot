"""
Recommendation confidence.

Blueprint §14: "Confidence should not be an arbitrary LLM number. Compute it
from data freshness, model uncertainty, lineup certainty, source reliability
and sensitivity to alternative assumptions."

Each factor is scored 0-1 and combined with fixed weights, and every factor is
returned alongside the total so a low score can be explained rather than just
displayed.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

# How stale data has to get before freshness is worthless
STALE_AFTER_HOURS = 24.0

WEIGHTS = {
    "data_freshness": 0.15,
    "minutes_certainty": 0.30,
    "model_precision": 0.20,
    "decision_margin": 0.25,
    "sample_depth": 0.10,
}


@dataclass
class ConfidenceBreakdown:
    total: float                  # 0-1
    percent: int                  # 0-100, for display
    factors: dict[str, float]
    notes: list[str]

    def as_dict(self) -> dict:
        return {
            "confidence": self.percent,
            "factors": {k: round(v, 3) for k, v in self.factors.items()},
            "weights": WEIGHTS,
            "notes": self.notes,
        }


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute_confidence(
    *,
    data_updated_at: datetime | None,
    p_start_in: float,
    p_start_out: float | None = None,
    variance: float,
    expected_gain: float,
    next_best_gain: float | None,
    matches_played: int,
) -> ConfidenceBreakdown:
    """
    Score a recommendation's reliability.

    `expected_gain` vs `next_best_gain` is the sensitivity check: if the top
    option barely beats the runner-up, the recommendation is fragile no matter
    how good the underlying data is.
    """
    notes: list[str] = []

    # ── Data freshness ───────────────────────────────────────────────────────
    if data_updated_at is None:
        freshness = 0.3
        notes.append("No data timestamp available")
    else:
        if data_updated_at.tzinfo is None:
            data_updated_at = data_updated_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - data_updated_at).total_seconds() / 3600
        freshness = _clamp(1.0 - age_hours / STALE_AFTER_HOURS)
        if age_hours > 12:
            notes.append(f"Data is {age_hours:.0f}h old — re-sync before acting")

    # ── Minutes certainty ────────────────────────────────────────────────────
    # The single biggest source of error in FPL projections is whether the
    # player actually plays.
    if p_start_out is None:
        minutes = _clamp(p_start_in)
    else:
        # A transfer depends on both sides: the incoming player starting and
        # the outgoing player's minutes being correctly assessed.
        minutes = _clamp(min(p_start_in, 0.5 + p_start_out * 0.5))
    if p_start_in < 0.6:
        notes.append(f"Incoming player start probability only {p_start_in:.0%}")

    # ── Model precision ──────────────────────────────────────────────────────
    # Variance is in points²; ~9 (a 3-point swing) is high for one gameweek.
    precision = _clamp(1.0 - variance / 9.0)

    # ── Decision margin ──────────────────────────────────────────────────────
    if next_best_gain is None:
        margin_score = 0.6
    else:
        margin = expected_gain - next_best_gain
        # A 2-point edge over the alternative is a confident call.
        margin_score = _clamp(margin / 2.0)
        if margin < 0.5:
            notes.append(
                f"Only {margin:+.2f} pts better than the next option — close call"
            )

    # ── Sample depth ─────────────────────────────────────────────────────────
    # Early in a season everything rests on priors.
    sample = _clamp(matches_played / 8.0)
    if matches_played < 4:
        notes.append(
            f"Only {matches_played} gameweek(s) of data — projections lean on "
            f"price-based priors"
        )

    factors = {
        "data_freshness": freshness,
        "minutes_certainty": minutes,
        "model_precision": precision,
        "decision_margin": margin_score,
        "sample_depth": sample,
    }
    total = sum(factors[k] * w for k, w in WEIGHTS.items())

    return ConfidenceBreakdown(
        total=round(total, 4),
        percent=int(round(total * 100)),
        factors=factors,
        notes=notes,
    )
