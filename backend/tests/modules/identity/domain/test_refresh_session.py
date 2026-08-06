from datetime import datetime, timezone

from app.modules.identity.domain.refresh_session import RefreshSession

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _session(**overrides) -> RefreshSession:
    defaults = dict(
        id="sess1",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash="hash",
        issued_at=_NOW,
        expires_at=_NOW,
        rotated_from=None,
        revoked_at=None,
        last_used_at=None,
    )
    defaults.update(overrides)
    return RefreshSession(**defaults)


def test_refresh_session_holds_every_field() -> None:
    session = _session(rotated_from="prev", revoked_at=_NOW, last_used_at=_NOW)

    assert session.id == "sess1"
    assert session.tenant_id == "t1"
    assert session.user_id == "u1"
    assert session.refresh_token_hash == "hash"
    assert session.rotated_from == "prev"
    assert session.revoked_at == _NOW
    assert session.last_used_at == _NOW


def test_is_revoked_reflects_revoked_at() -> None:
    assert _session(revoked_at=None).is_revoked is False
    assert _session(revoked_at=_NOW).is_revoked is True
