"""`ActionRiskReader`: `ActionRiskPort` adapter reading `action_permissions`
live (design.md §8.4 point 1, tasks.md task 11.4). Request-scoped, no
cross-request caching/singleton -- same contract and same rationale as
`PermissionService`'s own docstring (this package): a stale
`bulk_cancel_threshold`/`requires_hitl` cached across requests could let a
bulk-cancel or a newly-flagged action slip past HITL after a tenant admin
tightens the config via design.md §16's runtime-UPDATE escape hatch. Unlike
`PermissionService`, this adapter has no per-request memo at all (not even
an intra-request one) -- `scheduling_agent`/`hitl_approval` each call
`get()` at most once per node invocation, so a memo would add a mutable
dict for a saving that never materializes; simplicity wins over a
defensive cache nothing in this batch needs.

Same connection-ownership contract as every other Phase 3+ rbac adapter:
takes an already-open `AsyncConnection` from `app.db.runtime_engine`
(`app_runtime`, RLS-enforced) -- though `action_permissions` itself carries
no RLS (design.md §4.4: "catalogo global ... sin RLS"), so this reads the
same way regardless of which tenant's GUCs happen to be set on the
connection."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskConfig
from app.modules.governance.rbac.domain.permission import ActionKey

# Mirrors the DDL's own defaults (migration 7d88aa8f8a51) only in shape, NOT
# in value -- used solely when `action` has no row in `action_permissions`
# at all (an action key nobody has registered in the catalog yet, see
# `action_catalog.py`'s own docstring on why a new `authorize()` call site
# MUST register its key or become permanently undeniable/ungrantable).
# Deny-by-default is extended to HITL here: treat an unregistered action as
# requiring HITL approval and having zero bulk tolerance, rather than
# silently assuming the DDL's permissive defaults (`requires_hitl=false`,
# `bulk_cancel_threshold=3`) for an action this catalog has never seen --
# consistent with every other governance gate in this codebase (RBAC §5.2,
# RLS's own deny-by-default posture).
_UNREGISTERED_ACTION_RISK = ActionRiskConfig(requires_hitl=True, bulk_cancel_threshold=0)


class ActionRiskReader:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, action: ActionKey) -> ActionRiskConfig:
        result = await self._conn.execute(
            text("SELECT requires_hitl, bulk_cancel_threshold FROM action_permissions WHERE key = :action"),
            {"action": action},
        )
        row = result.first()
        if row is None:
            return _UNREGISTERED_ACTION_RISK
        return ActionRiskConfig(requires_hitl=row.requires_hitl, bulk_cancel_threshold=row.bulk_cancel_threshold)
