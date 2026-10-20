"""
conftest.py - session-scoped production-directory immutability guard.

Snapshots the full contents (mtime_ns + SHA-256) of data/, reports/, and status/
before any test executes, then verifies nothing changed after the session ends.
Any pytest test that accidentally touches those directories will be caught here.
"""
import hashlib
from pathlib import Path
import pytest


_PROTECTED = ["data", "reports", "status"]


def _snapshot(dirs: list) -> dict:
    snap = {}
    for d in dirs:
        p = Path(d)
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if not f.is_file():
                continue
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            snap[str(f)] = (f.stat().st_mtime_ns, h.hexdigest())
    return snap


@pytest.fixture(scope="session", autouse=True)
def guard_production_dirs():
    """
    Session fixture: take before-snapshot, yield, take after-snapshot.
    Fail the session if any file in data/, reports/, or status/ was added,
    removed, or byte-modified during the test run.
    """
    before = _snapshot(_PROTECTED)
    yield
    after = _snapshot(_PROTECTED)

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(
        p for p in set(before) & set(after) if before[p] != after[p]
    )

    violations = []
    for p in added:
        violations.append(f"ADDED:    {p}")
    for p in removed:
        violations.append(f"REMOVED:  {p}")
    for p in modified:
        violations.append(f"MODIFIED: {p}")

    if violations:
        pytest.fail(
            "pytest mutated protected production directories!\n"
            + "\n".join(violations)
        )
