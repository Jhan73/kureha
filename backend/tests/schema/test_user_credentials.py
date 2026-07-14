"""Task 4.1-4.3: user_credentials (design.md §17.3, gap fixed in migration
9f1c4a7b2e3d -- see that migration's docstring for why this is a dedicated
table rather than columns added to `users`)."""

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.schema.helpers import expect_violation, make_site, make_tenant, make_user, make_user_credentials


async def test_user_credentials_round_trips_email_and_auth_subject(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")

    await make_user_credentials(db_conn, tenant_id, user_id, email="staff@example.com", auth_subject="google-sub-1")

    row = (
        await db_conn.execute(
            sa.text("SELECT email, auth_subject, email_verified_at FROM user_credentials WHERE user_id = :u"),
            {"u": user_id},
        )
    ).one()
    assert row.email == "staff@example.com"
    assert row.auth_subject == "google-sub-1"
    assert row.email_verified_at is None


async def test_user_credentials_email_unique_within_tenant(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_a = await make_user(db_conn, tenant_id, site_id, role="reception")
    user_b = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_a, email="dup@example.com")

    async with expect_violation(db_conn, IntegrityError):
        await make_user_credentials(db_conn, tenant_id, user_b, email="dup@example.com")


async def test_user_credentials_email_may_repeat_across_tenants(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    user_a = await make_user(db_conn, tenant_a, site_a, role="reception")
    user_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    await make_user_credentials(db_conn, tenant_a, user_a, email="shared@example.com")
    second_id = await make_user_credentials(db_conn, tenant_b, user_b, email="shared@example.com")
    assert second_id is not None


async def test_user_credentials_auth_subject_allows_multiple_nulls(db_conn, tenant_id) -> None:
    """Plain UNIQUE(tenant_id, auth_subject), no partial index needed --
    Postgres treats every NULL as distinct in a multi-column UNIQUE."""
    site_id = await make_site(db_conn, tenant_id)
    user_a = await make_user(db_conn, tenant_id, site_id, role="reception")
    user_b = await make_user(db_conn, tenant_id, site_id, role="reception")

    await make_user_credentials(db_conn, tenant_id, user_a, email="a@example.com", auth_subject=None)
    second_id = await make_user_credentials(db_conn, tenant_id, user_b, email="b@example.com", auth_subject=None)
    assert second_id is not None


async def test_user_credentials_auth_subject_unique_within_tenant_when_present(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_a = await make_user(db_conn, tenant_id, site_id, role="reception")
    user_b = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_a, email="a@example.com", auth_subject="dup-sub")

    async with expect_violation(db_conn, IntegrityError):
        await make_user_credentials(db_conn, tenant_id, user_b, email="b@example.com", auth_subject="dup-sub")


async def test_user_credentials_user_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_b = await make_site(db_conn, tenant_b)
    user_of_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    async with expect_violation(db_conn):
        await make_user_credentials(db_conn, tenant_a, user_of_b, email="x@example.com")


async def test_user_credentials_one_row_per_user(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_id, email="first@example.com")

    async with expect_violation(db_conn, IntegrityError):
        await make_user_credentials(db_conn, tenant_id, user_id, email="second@example.com")
