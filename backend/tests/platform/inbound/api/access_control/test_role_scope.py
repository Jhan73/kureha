"""Task 10.2 (design.md §4.2, `SyncAppointmentToCalendar`'s module docstring,
`CalendarCredentialRepositoryPort`'s module docstring): the mid-transaction
`SET LOCAL app.role`/`app.patient_id`/`app.professional_id` re-scope that
lets ONE logical flow satisfy two different, mutually-exclusive RLS role
predicates on the SAME connection/transaction (patient-self-only
`calendar_credentials_self` interleaved with staff-only `calendar_sync_staff`
writes). Exercised against a real Postgres connection (`rls_conn`) --
`current_setting` is what every real RLS policy actually reads, so this is
the only trustworthy way to prove the re-scope takes effect."""

import sqlalchemy as sa

from app.platform.inbound.api.access_control.role_scope import scoped_as_patient, set_role_scope


async def test_set_role_scope_sets_role_and_patient_id(rls_conn) -> None:
    await set_role_scope(rls_conn, role="patient", patient_id="11111111-1111-1111-1111-111111111111")

    role = (await rls_conn.execute(sa.text("SELECT current_setting('app.role')"))).scalar_one()
    patient_id = (await rls_conn.execute(sa.text("SELECT current_setting('app.patient_id')"))).scalar_one()

    assert role == "patient"
    assert patient_id == "11111111-1111-1111-1111-111111111111"


async def test_set_role_scope_defaults_absent_ids_to_the_nil_uuid_sentinel(rls_conn) -> None:
    await set_role_scope(rls_conn, role="reception")

    patient_id = (await rls_conn.execute(sa.text("SELECT current_setting('app.patient_id')"))).scalar_one()
    professional_id = (await rls_conn.execute(sa.text("SELECT current_setting('app.professional_id')"))).scalar_one()

    assert patient_id == "00000000-0000-0000-0000-000000000000"
    assert professional_id == "00000000-0000-0000-0000-000000000000"


async def test_scoped_as_patient_switches_role_for_the_block_and_restores_after(rls_conn) -> None:
    await set_role_scope(rls_conn, role="reception")

    async with scoped_as_patient(rls_conn, patient_id="22222222-2222-2222-2222-222222222222", restore_role="reception"):
        role_inside = (await rls_conn.execute(sa.text("SELECT current_setting('app.role')"))).scalar_one()
        patient_id_inside = (await rls_conn.execute(sa.text("SELECT current_setting('app.patient_id')"))).scalar_one()
        assert role_inside == "patient"
        assert patient_id_inside == "22222222-2222-2222-2222-222222222222"

    role_after = (await rls_conn.execute(sa.text("SELECT current_setting('app.role')"))).scalar_one()
    patient_id_after = (await rls_conn.execute(sa.text("SELECT current_setting('app.patient_id')"))).scalar_one()
    assert role_after == "reception"
    assert patient_id_after == "00000000-0000-0000-0000-000000000000"


async def test_scoped_as_patient_restores_role_even_when_the_block_raises(rls_conn) -> None:
    await set_role_scope(rls_conn, role="admin")

    class _Boom(Exception):
        pass

    try:
        async with scoped_as_patient(rls_conn, patient_id="33333333-3333-3333-3333-333333333333", restore_role="admin"):
            raise _Boom("boom")
    except _Boom:
        pass

    role_after = (await rls_conn.execute(sa.text("SELECT current_setting('app.role')"))).scalar_one()
    assert role_after == "admin"
