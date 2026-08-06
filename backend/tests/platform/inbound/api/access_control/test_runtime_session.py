import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import create_engine
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.access_control.runtime_session import EngineRuntimeSession


def _actor(**overrides) -> LiveActor:
    defaults = dict(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="22222222-2222-2222-2222-222222222222",
        site_id="33333333-3333-3333-3333-333333333333",
        role="reception",
        status="active",
        patient_id=None,
        professional_id=None,
        staff_status=None,
    )
    defaults.update(overrides)
    return LiveActor(**defaults)


async def test_begin_opens_a_connection_as_app_runtime_with_gucs_set() -> None:
    engine = create_engine(settings.runtime_database_url, poolclass=NullPool)
    session = EngineRuntimeSession(engine)
    conn = None
    try:
        conn = await session.begin(_actor())

        current_user = (await conn.execute(sa.text("SELECT current_user"))).scalar_one()
        assert current_user == "app_runtime"

        tenant_id = (await conn.execute(sa.text("SELECT current_setting('app.tenant_id')"))).scalar_one()
        assert tenant_id == "22222222-2222-2222-2222-222222222222"
    finally:
        if conn is not None:
            await session.end(conn, commit=False)
        await engine.dispose()


async def test_end_commit_false_rolls_back_so_gucs_do_not_leak() -> None:
    engine = create_engine(settings.runtime_database_url, poolclass=NullPool)
    session = EngineRuntimeSession(engine)
    try:
        conn = await session.begin(_actor())
        await session.end(conn, commit=False)
        assert conn.closed
    finally:
        await engine.dispose()


async def test_end_commit_true_commits_and_closes() -> None:
    engine = create_engine(settings.runtime_database_url, poolclass=NullPool)
    session = EngineRuntimeSession(engine)
    try:
        conn = await session.begin(_actor())
        await session.end(conn, commit=True)
        assert conn.closed
    finally:
        await engine.dispose()
