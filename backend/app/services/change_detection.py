"""
Change detection and alerting.

Blueprint §2 calls for the product to be *proactive*: tell the user when
something relevant changed rather than making them look. That requires
diffing each sync against the last known state, which is what this module
does — no external service and no LLM involved.

Materiality is scored so the alert list stays useful. A 75% -> 50% doubt on a
bench player is not the same event as a starter being ruled out, and treating
them alike is how alert feeds get ignored.
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models.fpl import Player, Team, utcnow
from app.models.news import AvailabilityEvent, PlayerAvailabilitySnapshot, Alert
from app.services.news_parser import resolve_availability, STATUS_LABEL

# A change smaller than this is noise
MIN_AVAILABILITY_DELTA = 0.10

# Price change: `price_change_percent` is progress toward FPL's threshold.
# 90 was too strict to ever fire — observed live range is roughly -70..+70,
# because FPL resets progress after each change. 50 surfaces genuinely
# actionable movement in the read-only Price Watch view.
PRICE_WARN_PERCENT = 50.0

# Threshold for raising an *alert* about an imminent change. Higher than the
# watch-list threshold: an alert should mean "this is likely tonight", not
# "this is drifting upward".
PRICE_ALERT_PERCENT = 75.0


def _materiality(
    availability_before: float,
    availability_after: float,
    status_before: str,
    status_after: str,
) -> float:
    """
    How much a change matters, 0-1.

    Weighted by both the size of the swing and where it lands: dropping to
    zero is worse than the same-sized drop that leaves a player playable.
    """
    delta = abs(availability_after - availability_before)
    score = delta

    # Becoming completely unavailable is the most actionable event there is
    if availability_after == 0.0 and availability_before > 0.0:
        score = max(score, 0.9)
    # Returning to full fitness is nearly as useful
    elif availability_after >= 0.95 and availability_before < 0.75:
        score = max(score, 0.7)

    # A hard status transition is more reliable than a percentage nudge
    if status_before != status_after and status_after in ("i", "s", "u"):
        score = max(score, 0.85)

    return round(min(1.0, score), 3)


async def detect_changes(db: AsyncSession) -> dict:
    """
    Compare current player state against the stored snapshot and record events.

    Safe to run on every sync: it is idempotent in the sense that running it
    twice with no intervening FPL change produces no second event.
    """
    players = (await db.execute(select(Player))).scalars().all()
    snapshots = {
        s.player_id: s
        for s in (await db.execute(select(PlayerAvailabilitySnapshot))).scalars().all()
    }

    events: list[AvailabilityEvent] = []
    first_run = len(snapshots) == 0

    for p in players:
        availability, source, parsed = resolve_availability(
            status=p.status,
            chance_field=p.chance_of_playing_this_round,
            news=p.news,
        )

        snap = snapshots.get(p.id)

        if snap is None:
            # Establish a baseline without generating an event for it —
            # otherwise the first run would alert on all 609 players.
            db.add(PlayerAvailabilitySnapshot(
                player_id=p.id,
                status=p.status,
                chance_field=p.chance_of_playing_this_round,
                availability=availability,
                news_text=p.news or "",
                now_cost=p.now_cost,
                price_change_percent=p.price_change_percent or 0.0,
            ))
            continue

        status_changed = snap.status != p.status
        availability_delta = abs(availability - snap.availability)
        news_changed = (snap.news_text or "") != (p.news or "")
        price_changed = snap.now_cost != p.now_cost

        if status_changed or availability_delta >= MIN_AVAILABILITY_DELTA:
            if availability > snap.availability:
                event_type = "returned" if availability >= 0.95 else "chance_change"
            elif availability == 0.0:
                event_type = "departed" if parsed.cause == "transfer_out" else "ruled_out"
            else:
                event_type = "status_change" if status_changed else "chance_change"

            expected_return = None
            if parsed.expected_return:
                expected_return = datetime.combine(
                    parsed.expected_return, datetime.min.time(), tzinfo=timezone.utc
                )

            events.append(AvailabilityEvent(
                player_id=p.id,
                event_type=event_type,
                status_before=snap.status,
                status_after=p.status,
                availability_before=snap.availability,
                availability_after=availability,
                cause=parsed.cause,
                expected_return=expected_return,
                news_text=p.news or "",
                source="fpl_api",
                availability_source=source,
                materiality=_materiality(
                    snap.availability, availability, snap.status, p.status
                ),
                # Anything we could not parse is worth a human glance
                requires_review=bool(p.news) and not parsed.parsed,
            ))

        elif news_changed and p.news:
            # Text changed without moving the numbers — e.g. a return date
            # firmed up. Worth logging, rarely worth alerting.
            events.append(AvailabilityEvent(
                player_id=p.id,
                event_type="news_change",
                status_before=snap.status,
                status_after=p.status,
                availability_before=snap.availability,
                availability_after=availability,
                cause=parsed.cause,
                news_text=p.news,
                source="fpl_api",
                availability_source=source,
                materiality=0.15,
                requires_review=not parsed.parsed,
            ))

        if price_changed:
            direction = "rise" if p.now_cost > snap.now_cost else "fall"
            events.append(AvailabilityEvent(
                player_id=p.id,
                event_type="price_change",
                status_before=snap.status,
                status_after=p.status,
                availability_before=snap.availability,
                availability_after=availability,
                cause=f"price_{direction}",
                news_text=(
                    f"Price {direction}: "
                    f"£{snap.now_cost / 10:.1f}m -> £{p.now_cost / 10:.1f}m"
                ),
                source="fpl_api",
                availability_source=source,
                materiality=0.4,
            ))

        # ── Imminent price change ────────────────────────────────────────────
        # Warn BEFORE the change, not after. FPL publishes progress toward its
        # own threshold, so this needs no modelling — only a crossing check.
        #
        # Fire on the crossing rather than on the level: the percent creeps up
        # continuously, so alerting whenever it sits above the line would send
        # the same warning every sync until the price moved.
        elif not price_changed:
            before = snap.price_change_percent or 0.0
            now_pct = p.price_change_percent or 0.0

            crossed_rise = before < PRICE_ALERT_PERCENT <= now_pct
            crossed_fall = before > -PRICE_ALERT_PERCENT >= now_pct

            if crossed_rise or crossed_fall:
                direction = "rise" if crossed_rise else "fall"
                events.append(AvailabilityEvent(
                    player_id=p.id,
                    event_type="price_imminent",
                    status_before=snap.status,
                    status_after=p.status,
                    availability_before=snap.availability,
                    availability_after=availability,
                    cause=f"price_{direction}_imminent",
                    news_text=(
                        f"Price {direction} likely: {abs(now_pct):.0f}% of the way "
                        f"to FPL's threshold "
                        f"({p.net_transfers:+,} net transfers this gameweek)"
                    ),
                    source="fpl_api",
                    availability_source=source,
                    # High enough to alert, below a ruled-out injury.
                    materiality=0.55,
                ))

        # Roll the baseline forward
        snap.status = p.status
        snap.chance_field = p.chance_of_playing_this_round
        snap.availability = availability
        snap.news_text = p.news or ""
        snap.now_cost = p.now_cost
        snap.price_change_percent = p.price_change_percent or 0.0
        snap.updated_at = utcnow()

    for e in events:
        db.add(e)
    await db.commit()

    by_type: dict[str, int] = {}
    for e in events:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1

    return {
        "first_run": first_run,
        "baseline_created": first_run,
        "events_detected": len(events),
        "by_type": by_type,
        "needs_review": sum(1 for e in events if e.requires_review),
    }


async def generate_alerts(
    db: AsyncSession,
    fpl_entry_id: int,
    squad_player_ids: list[int],
    since: datetime | None = None,
    min_materiality: float = 0.3,
) -> dict:
    """
    Turn recent events into alerts for one manager's squad.

    Only events touching owned players become alerts — that is the whole point
    of the product being personal rather than a news feed.
    """
    q = (
        select(AvailabilityEvent, Player, Team.short_name)
        .join(Player, Player.id == AvailabilityEvent.player_id)
        .join(Team, Team.id == Player.team_id)
        .where(
            AvailabilityEvent.player_id.in_(squad_player_ids),
            AvailabilityEvent.materiality >= min_materiality,
        )
        .order_by(AvailabilityEvent.detected_at.desc())
    )
    if since:
        q = q.where(AvailabilityEvent.detected_at >= since)

    rows = (await db.execute(q)).all()

    # Do not re-alert on an event already recorded for this manager
    existing = set((await db.execute(
        select(Alert.event_id).where(Alert.fpl_entry_id == fpl_entry_id)
    )).scalars().all())

    created = 0
    for event, player, team_short in rows:
        if event.id in existing:
            continue

        if event.materiality >= 0.8:
            severity = "critical"
        elif event.materiality >= 0.45:
            severity = "warning"
        else:
            severity = "info"

        pct_before = int(round((event.availability_before or 0) * 100))
        pct_after = int(round((event.availability_after or 0) * 100))

        titles = {
            "ruled_out": f"{player.web_name} ruled out",
            "departed": f"{player.web_name} has left the league",
            "returned": f"{player.web_name} back to full fitness",
            "status_change": (
                f"{player.web_name}: "
                f"{STATUS_LABEL.get(event.status_before or 'a', '?')} → "
                f"{STATUS_LABEL.get(event.status_after or 'a', '?')}"
            ),
            "chance_change": (
                f"{player.web_name} availability {pct_before}% → {pct_after}%"
            ),
            "price_change": f"{player.web_name} price changed",
            "price_imminent": (
                f"{player.web_name} price likely to "
                f"{'rise' if (event.cause or '').endswith('rise_imminent') else 'fall'} soon"
            ),
            "news_change": f"{player.web_name} news updated",
        }

        db.add(Alert(
            fpl_entry_id=fpl_entry_id,
            event_id=event.id,
            player_id=player.id,
            severity=severity,
            title=titles.get(event.event_type, f"{player.web_name} update"),
            body=event.news_text or "",
            payload={
                "event_type": event.event_type,
                "team": team_short,
                "position": player.position,
                "price": round(player.now_cost / 10, 1),
                "cause": event.cause,
                "availability_before": event.availability_before,
                "availability_after": event.availability_after,
                "expected_return": (
                    event.expected_return.isoformat() if event.expected_return else None
                ),
                "materiality": event.materiality,
                "source": event.availability_source,
            },
        ))
        created += 1

    await db.commit()
    return {
        "fpl_entry_id": fpl_entry_id,
        "events_considered": len(rows),
        "alerts_created": created,
    }


async def price_watch(
    db: AsyncSession,
    player_ids: list[int] | None = None,
    threshold: float = PRICE_WARN_PERCENT,
) -> list[dict]:
    """
    Players close to a price change, using FPL's own published projections.

    No modelling needed: `price_change_percent` is progress toward the
    threshold and `price_change_projections` is FPL's own forecast.
    """
    q = (
        select(Player, Team.short_name)
        .join(Team, Team.id == Player.team_id)
        .where(
            (Player.price_change_percent >= threshold)
            | (Player.price_change_percent <= -threshold)
        )
    )
    if player_ids:
        q = q.where(Player.id.in_(player_ids))
    q = q.order_by(Player.price_change_percent.desc())

    rows = (await db.execute(q)).all()
    return [
        {
            "player_id": p.id,
            "name": p.web_name,
            "team": short,
            "price": round(p.now_cost / 10, 1),
            "direction": "rise" if p.price_change_percent > 0 else "fall",
            "percent_to_threshold": p.price_change_percent,
            "net_transfers_gw": p.net_transfers,
            "fpl_projections": p.price_change_projections,
        }
        for p, short in rows
    ]
