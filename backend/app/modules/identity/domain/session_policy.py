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
        """Time-window only; caller must confirm revocation was via rotation (successor exists)."""
        if session.revoked_at is None:
            return False
        return (now - session.revoked_at) <= grace_period
