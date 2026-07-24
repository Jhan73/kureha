"""`ActionRiskPort` (design.md §8.4 point 1, tasks.md task 11.4): reads the
LIVE `action_permissions.requires_hitl`/`bulk_cancel_threshold` values for a
single catalog action key. Closes a gap `scheduling_agent`'s own docstring
(tasks.md task 11.2) flagged explicitly: no port anywhere read either column
live before this task -- `scheduling_agent` used the DDL's documented
default (3) as a constructor-parameter placeholder. `hitl_approval` (this
same task) needs `requires_hitl` independently of whichever upstream
condition (`risk_level=="high"` or `requires_hitl`) routed execution into it
(design.md §8.3's `route_by_risk`, tasks.md task 11.6, not yet built),
since it must build correct audit-trail language/payload regardless of
which condition triggered the interrupt.

Deliberately narrower than `AuthorizationPort` (governance/rbac's existing
grant-resolution port, `application/ports/driven/authorization.py`): this
port answers "what risk configuration does this action carry", not "is this
actor allowed to perform it" -- a different question over the same table,
kept as a separate port rather than growing `AuthorizationPort`'s contract
with fields most of ITS callers (`AuthorizeAction`/`ListAllowedActions`)
never need."""

from dataclasses import dataclass
from typing import Protocol

from app.modules.governance.rbac.domain.permission import ActionKey


@dataclass(frozen=True, slots=True)
class ActionRiskConfig:
    requires_hitl: bool
    bulk_cancel_threshold: int


class ActionRiskPort(Protocol):
    async def get(self, action: ActionKey) -> ActionRiskConfig: ...
