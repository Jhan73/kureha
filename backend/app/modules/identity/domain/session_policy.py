"""`SessionPolicy` (design.md §17.4/ADR-15): pure rules governing refresh
lifecycle -- expiry and the 30s rotation grace period. No IO; `RefreshToken`
(application/use_cases/refresh_token.py) orchestrates these against
`SessionStorePort`/`ClockPort`, mirroring how `ConsentPolicy`/`PermissionPolicy`
keep the actual verdict logic here and IO in the use case."""

from datetime import datetime, timedelta

from app.modules.identity.domain.refresh_session import RefreshSession


class SessionPolicy:
    @staticmethod
    def is_expired(session: RefreshSession, *, now: datetime) -> bool:
        return session.expires_at <= now

    @staticmethod
    def is_within_rotation_grace_period(
        session: RefreshSession, *, now: datetime, grace_period: timedelta
    ) -> bool:
        """True when `session.revoked_at` is set and within `grace_period`
        of now. Purely a time-window check -- it does NOT know WHY
        `revoked_at` was set (`RefreshSession` carries no revocation-cause
        field). The caller MUST first confirm the revocation was actually
        caused by a rotation (e.g. via `SessionStorePort.find_successor`)
        before treating a `True` result as grace-period leniency -- design.md
        §17.4: a network-retry replay of the just-rotated refresh token is
        not theft, but a token revoked by logout/admin-revoke replayed in
        the same time window is not a rotation retry at all, and must never
        get this leniency (security fix)."""
        if session.revoked_at is None:
            return False
        return (now - session.revoked_at) <= grace_period
