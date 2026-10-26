"""
The admin dashboard: who uses the app and how they pay, and the few actions
support needs. Everything is read-mostly; every action is audited.

Sign-in accounts (emails, providers, sign-in dates) live in Supabase Auth and
are read through its admin API; teams, trials, subscriptions and settings
live here. Store subscriptions are never edited: Apple and Google own them,
and RevenueCat reflects them. Free access is a separate promotional
subscription that the store sync leaves alone (see revenuecat.ADMIN_GRANT_PRODUCT).
"""
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import FplAccount, Trial, User
from app.models.admin import AdminAudit
from app.models.billing import BillingEvent, Subscription
from app.models.feedback import AdviceCache
from app.models.news import TrackedManager
from app.models.notifications import Device, NotificationPreference, PushDelivery
from app.models.ops import JobRun
from app.models.fpl import utcnow
from app.services import supabase_admin
from app.services.entitlements import get_entitlement
from app.services.revenuecat import ADMIN_GRANT_PRODUCT, PROMOTIONAL

PAGE_SIZE = 50
AUTH_TTL_SECONDS = 120
STORE = {"APPLE", "GOOGLE", "STRIPE"}

_auth_cache: tuple[float, list[dict]] | None = None


def clear_cache() -> None:
    global _auth_cache
    _auth_cache = None


async def auth_users() -> dict[str, dict]:
    """Supabase's accounts by id, kept for two minutes: the list is paged through on every search."""
    global _auth_cache
    now = time.monotonic()
    if _auth_cache is None or now - _auth_cache[0] > AUTH_TTL_SECONDS:
        _auth_cache = (now, await supabase_admin.list_auth_users())
    return {u["id"]: u for u in _auth_cache[1]}


def mask_email(email: str | None) -> str | None:
    """an***@gmail.com: enough to recognise in a list, not to harvest from one."""
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _rows(db: AsyncSession) -> dict[str, dict]:
    """Everything held locally per user, in a handful of queries."""
    out: dict[str, dict] = {}

    def get(uid) -> dict:
        return out.setdefault(str(uid), {"teams": [], "devices": 0, "telegram": False})

    for u in (await db.execute(select(User))).scalars():
        get(u.id).update(created_at=u.created_at, last_seen_at=u.last_seen_at)
    for a in (await db.execute(select(FplAccount))).scalars():
        get(a.user_id)["teams"].append({"fpl_entry_id": a.fpl_entry_id, "team_name": a.team_name, "verified": a.verified_at is not None})
    for uid, n in (await db.execute(select(Device.user_id, func.count()).group_by(Device.user_id))).all():
        get(uid)["devices"] = n
    linked = set((await db.execute(
        select(TrackedManager.fpl_entry_id).where(TrackedManager.telegram_chat_id.is_not(None))
    )).scalars())
    for row in out.values():
        row["telegram"] = any(t["fpl_entry_id"] in linked for t in row["teams"])
    return out


async def _status(db: AsyncSession, user_id: uuid.UUID) -> dict:
    e = await get_entitlement(db, user_id)
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    granted = bool(sub and sub.provider == PROMOTIONAL and sub.product_id == ADMIN_GRANT_PRODUCT and e.premium)
    return {
        "status": "GRANTED" if granted else e.status,
        "premium": e.premium,
        "plan": e.plan,
        "provider": e.provider,
        "trial_ends_at": _iso(e.trial_ends_at),
        "subscription_ends_at": _iso(e.subscription_ends_at),
    }


async def list_users(db: AsyncSession, q: str = "", status: str | None = None, page: int = 1) -> dict:
    accounts = await auth_users()
    local = await _rows(db)
    q = q.strip().lower()
    rows = []
    for uid in set(accounts) | set(local):
        a, l = accounts.get(uid, {}), local.get(uid, {"teams": [], "devices": 0, "telegram": False})
        teams = l["teams"]
        if q and not (
            q in (a.get("email") or "").lower()
            or q in uid
            or any(q in (t["team_name"] or "").lower() or q == str(t["fpl_entry_id"]) for t in teams)
        ):
            continue
        rows.append((uid, a, l, teams))

    out = []
    for uid, a, l, teams in rows:
        s = await _status(db, uuid.UUID(uid))
        if status and s["status"] != status:
            continue
        out.append({
            "id": uid,
            "email": mask_email(a.get("email")),
            "providers": (a.get("app_metadata") or {}).get("providers") or [],
            "team": teams[0] if teams else None,
            **s,
            "created_at": a.get("created_at") or _iso(l.get("created_at")),
            "last_sign_in_at": a.get("last_sign_in_at"),
            "last_seen_at": _iso(l.get("last_seen_at")),
            "devices": l["devices"],
            "telegram": l["telegram"],
        })
    out.sort(key=lambda r: r["created_at"] or "", reverse=True)
    start = (page - 1) * PAGE_SIZE
    return {"total": len(out), "page": page, "page_size": PAGE_SIZE, "users": out[start:start + PAGE_SIZE]}


async def overview(db: AsyncSession) -> dict:
    accounts = await auth_users()
    local = await _rows(db)
    now = utcnow()
    ids = set(accounts) | set(local)

    statuses: dict[str, int] = {}
    plans: dict[str, int] = {"MONTHLY": 0, "ANNUAL": 0}
    for uid in ids:
        s = await _status(db, uuid.UUID(uid))
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
        if s["status"] == "ACTIVE" and s["provider"] in STORE and s["plan"] in plans:
            plans[s["plan"]] += 1

    created = [_parse(a.get("created_at")) for a in accounts.values()]

    def since(days: int) -> int:
        return sum(1 for c in created if c and c > now - timedelta(days=days))

    # Of the trials that ended in the last 30 days, how many became store subscriptions.
    ended = (await db.execute(
        select(Trial.user_id).where(Trial.user_id.is_not(None), Trial.ends_at <= now, Trial.ends_at > now - timedelta(days=30))
    )).scalars().all()
    paid = set((await db.execute(
        select(Subscription.user_id).where(Subscription.provider.in_(STORE))
    )).scalars())
    converted = sum(1 for u in ended if u in paid)

    last_refresh = await db.scalar(select(JobRun).where(JobRun.job == "refresh").order_by(JobRun.started_at.desc()).limit(1))
    prefs_off = await db.scalar(select(func.count()).select_from(NotificationPreference).where(NotificationPreference.live.is_(False)))
    return {
        "users": len(ids),
        "teams_connected": sum(len(l["teams"]) for l in local.values()),
        "statuses": statuses,
        "subscribers": plans,
        "signups": {"7d": since(7), "30d": since(30)},
        "trial_conversion_30d": {"ended": len(ended), "converted": converted},
        "push_devices": sum(l["devices"] for l in local.values()),
        "telegram_linked": sum(1 for l in local.values() if l["telegram"]),
        "live_alerts_off": prefs_off or 0,
        "advice_cached": await db.scalar(select(func.count()).select_from(AdviceCache)) or 0,
        "last_refresh": {
            "at": _iso(last_refresh.started_at), "ok": last_refresh.ok, "seconds": round(last_refresh.duration_seconds, 1),
        } if last_refresh else None,
    }


async def user_detail(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    auth = await supabase_admin.get_auth_user(user_id)
    local_user = await db.get(User, user_id)
    if auth is None and local_user is None:
        return None
    teams = (await db.execute(select(FplAccount).where(FplAccount.user_id == user_id))).scalars().all()
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    trial = await db.scalar(select(Trial).where(Trial.user_id == user_id))
    devices = (await db.execute(select(Device.platform, Device.last_seen_at).where(Device.user_id == user_id))).all()
    prefs = await db.get(NotificationPreference, user_id)
    tracked = {t.fpl_entry_id: t for t in (await db.execute(
        select(TrackedManager).where(TrackedManager.fpl_entry_id.in_([t.fpl_entry_id for t in teams]))
    )).scalars()} if teams else {}
    events = (await db.execute(
        select(BillingEvent).where(BillingEvent.app_user_id == str(user_id)).order_by(BillingEvent.id.desc()).limit(20)
    )).scalars().all()
    pushes = (await db.execute(
        select(PushDelivery).where(PushDelivery.user_id == user_id).order_by(PushDelivery.sent_at.desc()).limit(20)
    )).scalars().all()
    audit = (await db.execute(
        select(AdminAudit).where(AdminAudit.target_user_id == user_id).order_by(AdminAudit.created_at.desc()).limit(50)
    )).scalars().all()
    a = auth or {}
    return {
        "id": str(user_id),
        "email": a.get("email"),
        "providers": (a.get("app_metadata") or {}).get("providers") or [],
        "is_admin": (a.get("app_metadata") or {}).get("role") == "admin",
        "created_at": a.get("created_at") or _iso(local_user.created_at if local_user else None),
        "last_sign_in_at": a.get("last_sign_in_at"),
        "last_seen_at": _iso(local_user.last_seen_at) if local_user else None,
        "banned_until": a.get("banned_until"),
        "in_auth": auth is not None,
        **(await _status(db, user_id)),
        "teams": [
            {
                "fpl_entry_id": t.fpl_entry_id, "team_name": t.team_name, "manager_name": t.manager_name,
                "connected_at": _iso(t.created_at), "verified_at": _iso(t.verified_at),
                "telegram": bool(tracked.get(t.fpl_entry_id) and tracked[t.fpl_entry_id].telegram_chat_id),
            }
            for t in teams
        ],
        "subscription": {
            "provider": sub.provider, "status": sub.status, "plan": sub.plan, "product_id": sub.product_id,
            "expires_at": _iso(sub.expires_at), "is_sandbox": sub.is_sandbox, "synced_at": _iso(sub.synced_at),
            "granted": sub.product_id == ADMIN_GRANT_PRODUCT,
        } if sub else None,
        "trial": {"fpl_entry_id": trial.fpl_entry_id, "started_at": _iso(trial.started_at), "ends_at": _iso(trial.ends_at)} if trial else None,
        "devices": [{"platform": p, "last_seen_at": _iso(s)} for p, s in devices],
        "notifications": {k: (True if prefs is None else getattr(prefs, k)) for k in ("availability", "price", "deadline", "live")},
        "billing_events": [{"type": e.event_type, "at": _iso(e.received_at)} for e in events],
        "pushes": [{"kind": p.kind, "key": p.dedupe_key, "sent_at": _iso(p.sent_at)} for p in pushes],
        "audit": [audit_dict(x) for x in audit],
    }


def audit_dict(x: AdminAudit) -> dict:
    return {
        "id": x.id, "admin_user_id": str(x.admin_user_id), "action": x.action,
        "target_user_id": str(x.target_user_id) if x.target_user_id else None,
        "reason": x.reason, "detail": x.detail, "created_at": _iso(x.created_at),
    }


def record(db: AsyncSession, admin_id: uuid.UUID, action: str, target: uuid.UUID | None, reason: str, detail: dict | None = None) -> None:
    """Stage the audit row with the action, so both commit or neither does."""
    db.add(AdminAudit(admin_user_id=admin_id, action=action, target_user_id=target, reason=reason, detail=detail))


class ActionRefused(Exception):
    """The action does not apply to this user; the router turns it into 409."""


async def grant_access(db: AsyncSession, user_id: uuid.UUID, days: int) -> datetime:
    """
    Free access for `days`, added to any free access already running. Refused
    for someone paying through a store: their subscription is the store's.
    """
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    now = utcnow()
    if sub is not None and sub.provider in STORE and (await get_entitlement(db, user_id)).premium:
        raise ActionRefused("This user pays through the store; their subscription is managed there.")
    start = now
    if sub is not None and sub.product_id == ADMIN_GRANT_PRODUCT and sub.expires_at:
        current = sub.expires_at if sub.expires_at.tzinfo else sub.expires_at.replace(tzinfo=now.tzinfo)
        start = max(now, current)
    if sub is None:
        if await db.get(User, user_id) is None:
            db.add(User(id=user_id))
            await db.flush()
        sub = Subscription(user_id=user_id)
        db.add(sub)
    sub.provider = PROMOTIONAL
    sub.status = "ACTIVE"
    sub.plan = None
    sub.product_id = ADMIN_GRANT_PRODUCT
    sub.expires_at = start + timedelta(days=days)
    sub.grace_expires_at = None
    sub.is_sandbox = False
    sub.management_url = None
    sub.synced_at = now
    return sub.expires_at


async def end_grant(db: AsyncSession, user_id: uuid.UUID) -> None:
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is None or sub.product_id != ADMIN_GRANT_PRODUCT:
        raise ActionRefused("This user has no free access granted from the dashboard.")
    sub.status = "EXPIRED"
    sub.expires_at = utcnow()
