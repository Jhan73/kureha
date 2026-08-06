import sqlalchemy as sa

from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.access_control.session_context import set_session_context

_NIL_UUID = "00000000-0000-0000-0000-000000000000"


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


async def _current_setting(conn, name: str) -> str:
    result = await conn.execute(sa.text(f"SELECT current_setting('app.{name}')"))
    return result.scalar_one()


async def test_sets_tenant_site_role_user_gucs(rls_conn) -> None:
    actor = _actor()
    await set_session_context(rls_conn, actor)

    assert await _current_setting(rls_conn, "tenant_id") == actor.tenant_id
    assert await _current_setting(rls_conn, "site_id") == actor.site_id
    assert await _current_setting(rls_conn, "role") == "reception"
    assert await _current_setting(rls_conn, "user_id") == actor.user_id


async def test_missing_patient_and_professional_id_default_to_nil_uuid(rls_conn) -> None:
    actor = _actor(patient_id=None, professional_id=None)
    await set_session_context(rls_conn, actor)

    assert await _current_setting(rls_conn, "patient_id") == _NIL_UUID
    assert await _current_setting(rls_conn, "professional_id") == _NIL_UUID


async def test_patient_id_is_set_when_present(rls_conn) -> None:
    actor = _actor(role="patient", patient_id="44444444-4444-4444-4444-444444444444")
    await set_session_context(rls_conn, actor)

    assert await _current_setting(rls_conn, "patient_id") == "44444444-4444-4444-4444-444444444444"


async def test_professional_id_is_set_when_present(rls_conn) -> None:
    actor = _actor(role="professional", professional_id="55555555-5555-5555-5555-555555555555")
    await set_session_context(rls_conn, actor)

    assert await _current_setting(rls_conn, "professional_id") == "55555555-5555-5555-5555-555555555555"


class _RecordingConnection:
    """Wraps a real `AsyncConnection`, counting `execute()` calls -- proves
    `set_session_context` batches all six GUCs into a single round trip
    instead of six separate `conn.execute()` calls."""

    def __init__(self, real_conn) -> None:
        self._real = real_conn
        self.execute_calls: list[str] = []

    async def execute(self, clause):
        self.execute_calls.append(str(clause))
        return await self._real.execute(clause)


async def test_batches_all_six_gucs_into_a_single_round_trip(rls_conn) -> None:
    actor = _actor(role="professional", professional_id="55555555-5555-5555-5555-555555555555")
    recorder = _RecordingConnection(rls_conn)

    await set_session_context(recorder, actor)

    assert len(recorder.execute_calls) == 1
    # Functional correctness is unaffected by the batching -- same GUCs,
    # same values, still readable via the real underlying connection.
    assert await _current_setting(rls_conn, "tenant_id") == actor.tenant_id
    assert await _current_setting(rls_conn, "professional_id") == "55555555-5555-5555-5555-555555555555"
