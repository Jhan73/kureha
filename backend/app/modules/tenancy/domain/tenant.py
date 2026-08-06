from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str
    status: str
    llm_daily_budget_tokens: int

    @property
    def is_active(self) -> bool:
        return self.status == "active"
