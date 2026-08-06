from dataclasses import dataclass
from typing import Protocol

from app.modules.governance.rbac.domain.permission import ActionKey


@dataclass(frozen=True, slots=True)
class ActionRiskConfig:
    requires_hitl: bool
    bulk_cancel_threshold: int


class ActionRiskPort(Protocol):
    async def get(self, action: ActionKey) -> ActionRiskConfig: ...
