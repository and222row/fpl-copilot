"""
Regenerate the route table in docs/API.md from the app itself.

    python scripts/api_reference.py          # rewrite the table in place
    python scripts/api_reference.py --check  # exit 1 if it is out of date

The table sits between two marker comments; everything else in API.md is
written by hand. tests/test_docs.py runs the check, so a new or changed route
fails CI until the reference is regenerated.
"""
import os
import pathlib
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.routing import APIRoute  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402
from app.rate_limit import HEAVY, READ, UPSTREAM, limiter  # noqa: E402

DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "API.md"
BEGIN = "<!-- BEGIN GENERATED ROUTES -->"
END = "<!-- END GENERATED ROUTES -->"
TIERS = {HEAVY: "HEAVY", UPSTREAM: "UPSTREAM", READ: "READ"}


def _calls(dependant) -> set:
    found = set()
    for d in dependant.dependencies:
        if d.call is not None:
            found.add(d.call)
        found |= _calls(d)
    return found


def _access(path: str, calls: set) -> str:
    if path.endswith("/webhook"):
        return "webhook secret"
    if auth.require_job_token in calls:
        return "operator"
    parts = []
    if auth.require_manager_access in calls:
        parts.append("owner")
    if auth.require_premium in calls:
        parts.append("premium")
    if parts:
        return " + ".join(parts)
    if auth.current_user in calls:
        return "signed in"
    return "public"


def _summary(route: APIRoute) -> str:
    doc = (route.endpoint.__doc__ or "").strip()
    if not doc:
        return route.summary or route.name.replace("_", " ").capitalize()
    first = " ".join(doc.split("\n\n")[0].split())
    for stop in (". ", "? "):
        if stop in first:
            first = first.split(stop)[0] + stop.strip()
            break
    # Keep the table scannable: a long first sentence is cut at its first clause.
    if len(first) > 110 and ":" in first:
        first = first.split(":")[0] + "."
    return first.replace("|", "\\|")


def _limit(route: APIRoute) -> str:
    key = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
    limits = limiter._route_limits.get(key, [])
    if not limits:
        return "default"
    return ", ".join(TIERS.get(str(lim.limit).replace(" per 1 ", "/"), str(lim.limit)) for lim in limits)


def routes() -> list[tuple[str, str, str, str, str, str]]:
    rows = []

    def walk(items, prefix, inherited):
        for r in items:
            if isinstance(r, APIRoute):
                if not r.include_in_schema and "webhook" not in r.path:
                    continue
                calls = _calls(r.dependant) | {d.dependency for d in inherited}
                tag = (r.tags or ["root"])[0]
                for method in sorted(r.methods - {"HEAD"}):
                    rows.append((tag, method, prefix + r.path, _access(prefix + r.path, calls), _limit(r), _summary(r)))
            elif hasattr(r, "original_router") and hasattr(r, "include_context"):
                ctx = r.include_context
                walk(r.original_router.routes, prefix + ctx.prefix, [*inherited, *ctx.dependencies])

    walk(app.routes, "", [])
    return rows


def table() -> str:
    lines = []
    current = None
    for tag, method, path, access, limit, summary in routes():
        if tag != current:
            if current is not None:
                lines.append("")
            lines += [f"### {tag}", "", "| Method | Path | Access | Rate limit | Purpose |", "|---|---|---|---|---|"]
            current = tag
        lines.append(f"| {method} | `{path}` | {access} | {limit} | {summary} |")
    return "\n".join(lines)


def render(text: str) -> str:
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{table()}\n{END}{tail}"


def main() -> int:
    current = DOC.read_text(encoding="utf-8")
    updated = render(current)
    if "--check" in sys.argv:
        if updated != current:
            print("docs/API.md route table is out of date: run python scripts/api_reference.py")
            return 1
        return 0
    DOC.write_text(updated, encoding="utf-8", newline="\n")
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
