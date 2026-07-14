"""Task 2.6: staff_members, shifts (design.md §4.4, §6).

`staff_members` is operational registry only (no HR fields). Deactivation
never deletes (`status='inactive'` + `deactivated_at`). `shifts` gets the
same anti-overlap `EXCLUDE USING gist` pattern as `availability`/
`appointments` (design.md §4.1/§4.4), scoped per `staff_member_id`.
"""

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.schema.helpers import expect_violation, make_professional, make_site, make_tenant, make_user


async def make_staff_member(
    conn,
    tenant_id,
    site_id,
    *,
    name="Test Staff",
    operational_role="reception",
    user_id=None,
    professional_id=None,
) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO staff_members "
            "(tenant_id, site_id, user_id, professional_id, name, operational_role) "
            "VALUES (:tenant_id, :site_id, :user_id, :professional_id, :name, :operational_role) "
            "RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "user_id": user_id,
            "professional_id": professional_id,
            "name": name,
            "operational_role": operational_role,
        },
    )
    return str(result.scalar_one())


async def test_staff_member_defaults_to_active_status(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    staff_id = await make_staff_member(db_conn, tenant_id, site_id)

    row = (
        await db_conn.execute(
            sa.text("SELECT status, deactivated_at FROM staff_members WHERE id = :id"),
            {"id": staff_id},
        )
    ).one()
    assert row.status == "active"
    assert row.deactivated_at is None


async def test_staff_member_deactivation_does_not_delete_row(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    staff_id = await make_staff_member(db_conn, tenant_id, site_id)

    await db_conn.execute(
        sa.text(
            "UPDATE staff_members SET status = 'inactive', deactivated_at = now() WHERE id = :id"
        ),
        {"id": staff_id},
    )
    row = (
        await db_conn.execute(
            sa.text("SELECT status FROM staff_members WHERE id = :id"), {"id": staff_id}
        )
    ).one()
    assert row.status == "inactive"


async def test_staff_member_rejects_unknown_operational_role(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)

    async with expect_violation(db_conn):
        await make_staff_member(db_conn, tenant_id, site_id, operational_role="bogus")


async def test_staff_member_professional_cannot_register_twice_at_same_site(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    await make_staff_member(db_conn, tenant_id, site_id, professional_id=professional_id)

    async with expect_violation(db_conn, IntegrityError):
        await make_staff_member(db_conn, tenant_id, site_id, professional_id=professional_id)


async def test_staff_member_site_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_of_b = await make_site(db_conn, tenant_b)

    async with expect_violation(db_conn):
        await make_staff_member(db_conn, tenant_a, site_of_b)


async def test_staff_member_user_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    user_of_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    async with expect_violation(db_conn):
        await make_staff_member(db_conn, tenant_a, site_a, user_id=user_of_b)


async def test_staff_member_professional_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    professional_of_b = await make_professional(db_conn, tenant_b, site_b)

    async with expect_violation(db_conn):
        await make_staff_member(db_conn, tenant_a, site_a, professional_id=professional_of_b)


async def test_shift_rejects_overlap_for_same_staff_member(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    staff_id = await make_staff_member(db_conn, tenant_id, site_id)

    await db_conn.execute(
        sa.text(
            "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
            "VALUES (:tenant_id, :site_id, :staff_member_id, '2026-08-01T08:00Z', '2026-08-01T12:00Z')"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "staff_member_id": staff_id},
    )

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
                "VALUES (:tenant_id, :site_id, :staff_member_id, '2026-08-01T10:00Z', '2026-08-01T14:00Z')"
            ),
            {"tenant_id": tenant_id, "site_id": site_id, "staff_member_id": staff_id},
        )


async def test_shift_allows_non_overlapping_windows_for_same_staff_member(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    staff_id = await make_staff_member(db_conn, tenant_id, site_id)

    await db_conn.execute(
        sa.text(
            "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
            "VALUES (:tenant_id, :site_id, :staff_member_id, '2026-08-01T08:00Z', '2026-08-01T12:00Z')"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "staff_member_id": staff_id},
    )
    result = await db_conn.execute(
        sa.text(
            "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
            "VALUES (:tenant_id, :site_id, :staff_member_id, '2026-08-01T12:00Z', '2026-08-01T16:00Z') "
            "RETURNING id"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "staff_member_id": staff_id},
    )
    assert result.scalar_one() is not None


async def test_shift_rejects_ends_at_before_starts_at(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    staff_id = await make_staff_member(db_conn, tenant_id, site_id)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
                "VALUES (:tenant_id, :site_id, :staff_member_id, '2026-08-01T12:00Z', '2026-08-01T08:00Z')"
            ),
            {"tenant_id": tenant_id, "site_id": site_id, "staff_member_id": staff_id},
        )


async def test_shift_staff_member_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    staff_of_b = await make_staff_member(db_conn, tenant_b, site_b)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
                "VALUES (:tenant_id, :site_id, :staff_member_id, '2026-08-01T08:00Z', '2026-08-01T12:00Z')"
            ),
            {"tenant_id": tenant_a, "site_id": site_a, "staff_member_id": staff_of_b},
        )
