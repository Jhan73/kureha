"""`LiveActor` (design.md §4.2 "Gate de estado activo vivo", tasks.md task
5.1): the access-control middleware's live-resolved snapshot of a `users`
row LEFT JOIN `staff_members` -- the SAME lookup that projects `tenant_id`/
`site_id`/`role`/`user_id` into `SET LOCAL app.*` GUCs also pays for this
gate, so it is resolved once per request, not as a separate query.

Deliberately its own value object, not `app.modules.identity.domain.
user_account.UserAccount` -- `UserAccount` has no `staff_status` field
(design.md §4.1: the `staff_members` table is not identity's concern, it
belongs to the not-yet-built `staff` module). Resolving BOTH tables in one
query is a platform-layer ("system stage") concern per design.md §4.4's
note on `user_sessions`/`rate_counters`: "vive fuera de las policies de dato
de paciente... no la lee el dominio de negocio"."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveActor:
    user_id: str
    tenant_id: str
    site_id: str
    role: str
    status: str
    patient_id: str | None
    professional_id: str | None
    staff_status: str | None
    """`staff_members.status` for the ONE `staff_members` row (if any) whose
    `user_id` matches this actor. `None` when no such row exists (e.g. a
    `patient` actor, or staff who never got an operational registry entry)
    -- see `is_active`'s docstring for why `None` here does not gate."""

    @property
    def is_active(self) -> bool:
        """design.md §4.2: "el actor se considera activo solo si AMBOS
        campos son 'active'". When there is no `staff_members` row at all
        (`staff_status is None`), there is nothing to gate on beyond
        `users.status` -- absence of a staff registry entry is not itself a
        deactivation signal."""
        if self.status != "active":
            return False
        return self.staff_status is None or self.staff_status == "active"
