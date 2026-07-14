"""Task 4.4: `SessionPolicy` -- pure rules for refresh-token expiry and the
30s rotation grace period (design.md §17.4/ADR-15). No IO."""

from datetime import datetime, timedelta, timezone

from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.session_policy import SessionPolicy

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_GRACE = timedelta(seconds=30)


def _session(**overrides) -> RefreshSession:
    defaults = dict(
        id="s1",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash="hash",
        issued_at=_NOW - timedelta(days=1),
        expires_at=_NOW + timedelta(days=29),
        rotated_from=None,
        revoked_at=None,
        last_used_at=None,
    )
    defaults.update(overrides)
    return RefreshSession(**defaults)


def test_is_expired_true_when_expires_at_in_the_past() -> None:
    session = _session(expires_at=_NOW - timedelta(seconds=1))
    assert SessionPolicy.is_expired(session, now=_NOW) is True


def test_is_expired_false_when_expires_at_in_the_future() -> None:
    session = _session(expires_at=_NOW + timedelta(days=1))
    assert SessionPolicy.is_expired(session, now=_NOW) is False


def test_is_expired_true_at_exact_boundary() -> None:
    session = _session(expires_at=_NOW)
    assert SessionPolicy.is_expired(session, now=_NOW) is True


def test_not_within_grace_period_when_never_revoked() -> None:
    session = _session(revoked_at=None)
    assert SessionPolicy.is_within_rotation_grace_period(session, now=_NOW, grace_period=_GRACE) is False


def test_within_grace_period_just_inside_the_window() -> None:
    session = _session(revoked_at=_NOW - timedelta(seconds=29))
    assert SessionPolicy.is_within_rotation_grace_period(session, now=_NOW, grace_period=_GRACE) is True


def test_within_grace_period_at_exact_boundary() -> None:
    session = _session(revoked_at=_NOW - timedelta(seconds=30))
    assert SessionPolicy.is_within_rotation_grace_period(session, now=_NOW, grace_period=_GRACE) is True


def test_outside_grace_period_past_the_window() -> None:
    session = _session(revoked_at=_NOW - timedelta(seconds=31))
    assert SessionPolicy.is_within_rotation_grace_period(session, now=_NOW, grace_period=_GRACE) is False
