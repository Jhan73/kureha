from datetime import timedelta
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


class AccessTokenIssuerPort(Protocol):
    async def issue(self, ctx: TenantContext, *, ttl: timedelta) -> str:
        """Signed access token from ctx; stateless, not persisted."""
        ...
