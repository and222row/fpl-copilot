"""
Every API route with its full path and effective dependencies.

The structural security tests (ownership, premium, guarded writes) iterate
this. FastAPI 0.13x+ stores included routers as lazy wrappers instead of
flattening them into app.routes, which silently emptied a plain app.routes
walk and let those tests pass while checking nothing.
test_route_walker_sees_every_documented_route guards against that recurring.
"""
from dataclasses import dataclass, field

from fastapi.routing import APIRoute


@dataclass
class RouteInfo:
    path: str
    methods: set[str]
    dependencies: list = field(default_factory=list)


def api_routes(app) -> list[RouteInfo]:
    found: list[RouteInfo] = []

    def walk(routes, prefix: str, inherited: list) -> None:
        for r in routes:
            if isinstance(r, APIRoute):
                found.append(RouteInfo(prefix + r.path, set(r.methods), [*inherited, *r.dependencies]))
            elif hasattr(r, "original_router") and hasattr(r, "include_context"):
                ctx = r.include_context
                walk(r.original_router.routes, prefix + ctx.prefix, [*inherited, *ctx.dependencies])

    walk(app.routes, "", [])
    return found
