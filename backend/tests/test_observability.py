"""
Observability and security-header tests.

The redaction tests matter most: a log aggregator is a place secrets go to live
forever, and `extra={...}` makes it easy to pass a whole settings object by
accident.
"""
import json
import logging
import pytest
from app.observability import JsonFormatter, redact, request_id_var, REDACTED_KEYS


# ── Redaction ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(REDACTED_KEYS))
def test_every_sensitive_key_is_redacted(key):
    assert redact("super-secret-value", key) == "***"


def test_redaction_is_case_insensitive():
    assert redact("v", "API_KEY") == "***"
    assert redact("v", "Authorization") == "***"


def test_redaction_recurses_into_dicts():
    out = redact({"user": "ok", "password": "hunter2", "nested": {"token": "abc"}})
    assert out["user"] == "ok"
    assert out["password"] == "***"
    assert out["nested"]["token"] == "***"


def test_redaction_recurses_into_lists():
    out = redact([{"api_key": "x"}, {"safe": "y"}])
    assert out[0]["api_key"] == "***"
    assert out[1]["safe"] == "y"


def test_non_sensitive_values_pass_through():
    assert redact(42, "count") == 42
    assert redact("GET", "method") == "GET"


def test_a_full_connection_string_is_redacted():
    """The realistic accident: logging settings wholesale."""
    out = redact({
        "database_url": "postgresql://user:pw@host/db",
        "redis_url": "rediss://:pw@host:6379",
        "environment": "production",
    })
    assert out["database_url"] == "***"
    assert out["redis_url"] == "***"
    assert out["environment"] == "production"


# ── JSON formatter ───────────────────────────────────────────────────────────

def _record(**extra) -> logging.LogRecord:
    r = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_formatter_emits_valid_json():
    parsed = json.loads(JsonFormatter().format(_record()))
    assert parsed["message"] == "hello"
    assert parsed["level"] == "INFO"
    assert "ts" in parsed


def test_formatter_includes_extra_fields():
    parsed = json.loads(JsonFormatter().format(_record(path="/api/v1/health", status=200)))
    assert parsed["path"] == "/api/v1/health"
    assert parsed["status"] == 200


def test_formatter_redacts_extra_fields():
    parsed = json.loads(JsonFormatter().format(_record(api_key="leak-me")))
    assert parsed["api_key"] == "***"


def test_formatter_includes_request_id_when_set():
    token = request_id_var.set("abc123")
    try:
        parsed = json.loads(JsonFormatter().format(_record()))
        assert parsed["request_id"] == "abc123"
    finally:
        request_id_var.reset(token)


def test_formatter_handles_non_serialisable_values():
    parsed = json.loads(JsonFormatter().format(_record(obj=object())))
    assert "obj" in parsed          # coerced via default=str, not crashed


def test_formatter_includes_exception_text():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        r = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    parsed = json.loads(JsonFormatter().format(r))
    assert "ValueError: boom" in parsed["exception"]


# ── Middleware behaviour ─────────────────────────────────────────────────────

async def test_request_id_header_is_returned(client):
    r = await client.get("/")
    assert r.headers.get("X-Request-ID")


async def test_supplied_request_id_is_echoed_back(client):
    r = await client.get("/", headers={"X-Request-ID": "trace-me-123"})
    assert r.headers["X-Request-ID"] == "trace-me-123"


async def test_response_time_header_present(client):
    r = await client.get("/")
    assert float(r.headers["X-Response-Time-ms"]) >= 0


@pytest.mark.parametrize("header,value", [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
])
async def test_security_headers_are_set(client, header, value):
    r = await client.get("/")
    assert r.headers[header] == value


async def test_error_response_carries_a_request_id(client):
    """A 404 should still be traceable back to its logs."""
    r = await client.get("/api/v1/fpl/players/999999")
    assert r.status_code == 404
    assert r.headers.get("X-Request-ID")


# ── Freshness endpoint ───────────────────────────────────────────────────────

async def test_freshness_reports_missing_on_empty_database(client):
    r = await client.get("/api/v1/health/freshness")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stale"
    assert body["data_sets"]["players"]["status"] == "missing"
    assert body["hint"]


async def test_freshness_reports_counts_and_matches_played(client):
    body = (await client.get("/api/v1/health/freshness")).json()
    assert set(body["row_counts"]) == {
        "players", "fixtures", "gameweeks", "projections",
    }
    assert body["matches_played"] == 0


async def test_freshness_marks_recent_data_fresh(client, session):
    from tests.conftest import make_team, make_player
    session.add(make_team(1))
    await session.flush()
    session.add(make_player(1, team_id=1))
    await session.commit()

    body = (await client.get("/api/v1/health/freshness")).json()
    assert body["data_sets"]["players"]["status"] == "fresh"
    assert body["data_sets"]["players"]["age_minutes"] < 5
