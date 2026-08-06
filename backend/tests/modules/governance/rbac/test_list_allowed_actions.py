import pytest

from app.modules.governance.rbac.application.use_cases.list_allowed_actions import ListAllowedActions
from app.shared_kernel.tenant_context import TenantContext


class _FakeAuthorizationPort:
    async def is_allowed(self, ctx: TenantContext, action: str) -> bool:
        raise NotImplementedError

    async def list_allowed_actions(self, ctx: TenantContext) -> set[str]:
        return {"appointment:view", "appointment:create"}


@pytest.mark.asyncio
async def test_returns_the_ports_allowed_action_set() -> None:
    use_case = ListAllowedActions(_FakeAuthorizationPort())
    ctx = TenantContext(tenant_id="t1", role="patient", actor_id="u1")

    result = await use_case.execute(ctx)

    assert result == {"appointment:view", "appointment:create"}
