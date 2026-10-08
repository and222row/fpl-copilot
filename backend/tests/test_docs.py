"""
The documentation stays true to the code.

Docs that describe routes or settings that no longer exist, or miss new ones,
are worse than none: a new developer trusts them. These fail when the API
reference, the environment variable list or a link between documents falls
behind.
"""
import importlib.util
import pathlib
import re

import pytest

from app.config import Settings

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    *sorted((ROOT / "docs").glob("*.md")),
    ROOT / "mobile" / "README.md",
    ROOT / "mobile" / ".maestro" / "README.md",
    ROOT / "frontend" / "README.md",
]
ENV_DOC = (ROOT / "docs" / "ENVIRONMENT_VARIABLES.md").read_text(encoding="utf-8")


def _load_api_reference():
    path = ROOT / "backend" / "scripts" / "api_reference.py"
    spec = importlib.util.spec_from_file_location("api_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_api_reference_matches_the_routes():
    ref = _load_api_reference()
    current = ref.DOC.read_text(encoding="utf-8")
    assert ref.render(current) == current, (
        "docs/API.md is out of date: run `python scripts/api_reference.py` in backend/"
    )


def test_api_reference_lists_every_route():
    """Independent of the generator: the route walker's paths all appear."""
    from app.main import app
    from tests.routes import api_routes

    text = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    missing = [r.path for r in api_routes(app) if f"`{r.path}`" not in text and r.path.startswith("/api")]
    assert not missing


@pytest.mark.parametrize("name", sorted(f.upper() for f in Settings.model_fields))
def test_every_backend_setting_is_documented(name):
    assert f"`{name}`" in ENV_DOC


def _public_vars() -> set[str]:
    sources = [
        *(ROOT / "mobile" / "src").rglob("*.ts"),
        *(ROOT / "mobile" / "src").rglob("*.tsx"),
        ROOT / "mobile" / "app.config.ts",
        *(ROOT / "frontend" / "src").rglob("*.ts"),
        *(ROOT / "frontend" / "src").rglob("*.tsx"),
        ROOT / "frontend" / "next.config.ts",
    ]
    found = set()
    for path in sources:
        if "__tests__" in path.parts:
            continue
        found |= set(re.findall(r"process\.env\.((?:EXPO|NEXT)_PUBLIC_[A-Z0-9_]+|[A-Z][A-Z0-9_]+)",
                                path.read_text(encoding="utf-8")))
    return found - {"NODE_ENV", "EXPO_OS"}


def test_every_client_variable_is_documented():
    missing = sorted(v for v in _public_vars() if f"`{v}`" not in ENV_DOC and v not in ENV_DOC)
    assert not missing


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = heading.strip().lower().replace("`", "")
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(path: pathlib.Path) -> set[str]:
    in_code = False
    anchors = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("#"):
            anchors.add(_slug(line.lstrip("#")))
    return anchors


def _links(path: pathlib.Path):
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for target in re.findall(r"\]\(([^)\s]+)\)", line):
            if not re.match(r"[a-z]+:", target):
                yield target


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_links_between_documents_resolve(doc):
    broken = []
    for target in _links(doc):
        file_part, _, anchor = target.partition("#")
        dest = (doc.parent / file_part).resolve() if file_part else doc
        if not dest.exists():
            broken.append(target)
        elif anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
            broken.append(target)
    assert not broken
