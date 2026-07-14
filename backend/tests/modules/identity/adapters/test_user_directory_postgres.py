"""Task 4.1/4.3: `PostgresUserDirectory` -- `UserDirectoryPort` adapter over
`users` JOIN `user_credentials` (design.md §17.3, migration 9f1c4a7b2e3d).

Uses `db_conn` (the `app_user`/elevated connection), NOT `rls_conn` -- this
adapter is wired, in the composition root, against `app.db.engine` (see
`UserDirectoryPort`'s docstring for why: pre-auth resolution runs before any
`app.*` GUC exists, the same elevated-connection contract Alembic itself
uses)."""

import pytest
from tests.schema.helpers import make_site, make_tenant, make_user, make_user_credentials

from app.modules.identity.adapters.outbound.postgres.user_directory import PostgresUserDirectory
from app.modules.identity.domain.errors import UnmappedIdentityError


async def test_find_by_email_returns_none_when_no_match(db_conn, tenant_id) -> None:
    directory = PostgresUserDirectory(db_conn)
    assert await directory.find_by_email(tenant_id, "nobody@example.com") is None


async def test_find_by_email_returns_the_joined_user_account(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_id, email="staff@example.com", auth_subject="google-sub-1")

    directory = PostgresUserDirectory(db_conn)
    account = await directory.find_by_email(tenant_id, "staff@example.com")

    assert account is not None
    assert account.id == user_id
    assert account.tenant_id == tenant_id
    assert account.site_id == site_id
    assert account.role == "reception"
    assert account.status == "active"
    assert account.email == "staff@example.com"
    assert account.auth_subject == "google-sub-1"
    assert account.email_verified_at is None


async def test_find_by_email_is_scoped_to_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_b = await make_site(db_conn, tenant_b)
    user_b = await make_user(db_conn, tenant_b, site_b, role="reception")
    await make_user_credentials(db_conn, tenant_b, user_b, email="shared@example.com")

    directory = PostgresUserDirectory(db_conn)
    assert await directory.find_by_email(tenant_a, "shared@example.com") is None


async def test_find_by_auth_subject_returns_the_joined_user_account(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="admin")
    await make_user_credentials(db_conn, tenant_id, user_id, email="admin@example.com", auth_subject="google-sub-9")

    directory = PostgresUserDirectory(db_conn)
    account = await directory.find_by_auth_subject(tenant_id, "google-sub-9")

    assert account is not None
    assert account.id == user_id
    assert account.role == "admin"


async def test_find_by_auth_subject_returns_none_when_no_match(db_conn, tenant_id) -> None:
    directory = PostgresUserDirectory(db_conn)
    assert await directory.find_by_auth_subject(tenant_id, "never-linked") is None


async def test_get_by_id_returns_the_current_row_live(db_conn, tenant_id) -> None:
    import sqlalchemy as sa

    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_id, email="staff@example.com")

    directory = PostgresUserDirectory(db_conn)
    before = await directory.get_by_id(tenant_id, user_id)
    assert before.status == "active"

    await db_conn.execute(sa.text("UPDATE users SET status = 'inactive' WHERE id = :id"), {"id": user_id})

    after = await directory.get_by_id(tenant_id, user_id)
    assert after.status == "inactive"


async def test_get_by_id_returns_none_for_unknown_user(db_conn, tenant_id) -> None:
    directory = PostgresUserDirectory(db_conn)
    assert await directory.get_by_id(tenant_id, "00000000-0000-0000-0000-000000000000") is None


async def test_link_auth_subject_sets_subject_and_verification_timestamp(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_id, email="patient@example.com")

    directory = PostgresUserDirectory(db_conn)
    linked = await directory.link_auth_subject(tenant_id, user_id, auth_subject="google-sub-linked", email_verified=True)

    assert linked.auth_subject == "google-sub-linked"
    assert linked.email_verified_at is not None

    refetched = await directory.find_by_auth_subject(tenant_id, "google-sub-linked")
    assert refetched is not None
    assert refetched.id == user_id


async def test_link_auth_subject_without_email_verified_leaves_verification_timestamp_null(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_credentials(db_conn, tenant_id, user_id, email="staff@example.com")

    directory = PostgresUserDirectory(db_conn)
    linked = await directory.link_auth_subject(tenant_id, user_id, auth_subject="google-sub-x", email_verified=False)

    assert linked.email_verified_at is None


async def test_link_auth_subject_raises_when_there_is_no_matching_credentials_row(db_conn, tenant_id) -> None:
    directory = PostgresUserDirectory(db_conn)

    with pytest.raises(UnmappedIdentityError):
        await directory.link_auth_subject(
            tenant_id, "00000000-0000-0000-0000-000000000000", auth_subject="google-sub-ghost", email_verified=True
        )
