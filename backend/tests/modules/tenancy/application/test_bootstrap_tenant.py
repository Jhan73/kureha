import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.tenancy.application.use_cases.bootstrap_tenant import BootstrapTenant
from app.modules.tenancy.domain.errors import TenantAlreadyExistsError
from app.modules.tenancy.domain.tenant_bootstrap import BootstrapTenantCommand
from app.shared_kernel.errors import ValidationError


class _FakeIdGenerator:
    def __init__(self, ids: list[str]) -> None:
        self._ids = list(ids)

    def new_id(self) -> str:
        return self._ids.pop(0)


class _FakeTenantProvisioningRepository:
    _DB_GENERATED_TENANT_ID = "db-generated-tenant-id"

    def __init__(self, *, raises: Exception | None = None, calls: list[str] | None = None) -> None:
        self._raises = raises
        self._calls = calls if calls is not None else []
        self.provisioned: list[dict] = []

    async def provision(self, **kwargs) -> str:
        self._calls.append("repository.provision")
        self.provisioned.append(kwargs)
        if self._raises:
            raise self._raises
        supplied = kwargs["tenant_id"]
        return supplied if supplied is not None else self._DB_GENERATED_TENANT_ID


class _FakeRbacSeeder:
    def __init__(self, *, calls: list[str] | None = None) -> None:
        self._calls = calls if calls is not None else []
        self.seeded_tenant_ids: list[str] = []

    async def seed_for_tenant(self, tenant_id: str) -> None:
        self._calls.append("rbac_seeder.seed_for_tenant")
        self.seeded_tenant_ids.append(tenant_id)


class _FakeAuditLog:
    def __init__(self, *, calls: list[str] | None = None) -> None:
        self._calls = calls if calls is not None else []
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self._calls.append("audit_log.record")
        self.recorded.append(entry)
        return "audit-1"


def _build(repository=None, rbac_seeder=None, audit_log=None, id_generator=None) -> BootstrapTenant:
    repository = repository or _FakeTenantProvisioningRepository()
    rbac_seeder = rbac_seeder or _FakeRbacSeeder()
    audit_log = audit_log or _FakeAuditLog()
    id_generator = id_generator or _FakeIdGenerator(["site-1", "user-1"])
    return BootstrapTenant(repository, rbac_seeder, audit_log, id_generator)


async def test_bootstraps_a_new_tenant_end_to_end() -> None:
    repository = _FakeTenantProvisioningRepository()
    rbac_seeder = _FakeRbacSeeder()
    audit_log = _FakeAuditLog()
    use_case = _build(repository, rbac_seeder, audit_log)

    command = BootstrapTenantCommand(name="Clinica Test", admin_email="admin@example.com")
    result = await use_case.execute(command, operator_key_id="ops-key-1")

    db_generated_id = _FakeTenantProvisioningRepository._DB_GENERATED_TENANT_ID
    assert result.tenant_id == db_generated_id
    assert result.site_id == "site-1"
    assert result.admin_user_id == "user-1"
    assert result.admin_email == "admin@example.com"

    assert repository.provisioned == [
        {
            "tenant_id": None,
            "name": "Clinica Test",
            "site_id": "site-1",
            "site_name": "Clinica Test Main Site",
            "admin_user_id": "user-1",
            "admin_email": "admin@example.com",
        }
    ]
    assert rbac_seeder.seeded_tenant_ids == [db_generated_id]

    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.tenant_id == db_generated_id
    assert entry.site_id == "site-1"
    assert entry.actor_type == AuditActorType.SYSTEM
    assert entry.action == AuditAction.TENANT_BOOTSTRAP
    assert entry.object_type == "tenant"
    assert entry.object_id == db_generated_id
    assert entry.payload["operator_key_id"] == "ops-key-1"
    assert entry.payload["admin_email"] == "admin@example.com"


async def test_uses_the_client_provided_tenant_id_when_given() -> None:
    repository = _FakeTenantProvisioningRepository()
    id_generator = _FakeIdGenerator(["site-1", "user-1"])
    use_case = _build(repository, id_generator=id_generator)

    command = BootstrapTenantCommand(
        name="Clinica Test",
        admin_email="admin@example.com",
        tenant_id="11111111-1111-1111-1111-111111111111",
    )
    result = await use_case.execute(command)

    assert result.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert repository.provisioned[0]["tenant_id"] == "11111111-1111-1111-1111-111111111111"


async def test_invocation_order_is_repository_then_rbac_seeder_then_audit() -> None:
    calls: list[str] = []
    repository = _FakeTenantProvisioningRepository(calls=calls)
    rbac_seeder = _FakeRbacSeeder(calls=calls)
    audit_log = _FakeAuditLog(calls=calls)
    use_case = _build(repository, rbac_seeder, audit_log)

    await use_case.execute(BootstrapTenantCommand(name="Clinica Test", admin_email="admin@example.com"))

    assert calls == ["repository.provision", "rbac_seeder.seed_for_tenant", "audit_log.record"]


async def test_repository_failure_skips_rbac_seeding_and_audit() -> None:
    calls: list[str] = []
    repository = _FakeTenantProvisioningRepository(raises=TenantAlreadyExistsError(), calls=calls)
    rbac_seeder = _FakeRbacSeeder(calls=calls)
    audit_log = _FakeAuditLog(calls=calls)
    use_case = _build(repository, rbac_seeder, audit_log)

    with pytest.raises(TenantAlreadyExistsError):
        await use_case.execute(BootstrapTenantCommand(name="Clinica Test", admin_email="admin@example.com"))

    assert calls == ["repository.provision"]
    assert rbac_seeder.seeded_tenant_ids == []
    assert audit_log.recorded == []


async def test_invalid_name_is_rejected_before_touching_any_port() -> None:
    repository = _FakeTenantProvisioningRepository()
    rbac_seeder = _FakeRbacSeeder()
    audit_log = _FakeAuditLog()
    use_case = _build(repository, rbac_seeder, audit_log)

    with pytest.raises(ValidationError):
        await use_case.execute(BootstrapTenantCommand(name="  ", admin_email="admin@example.com"))

    assert repository.provisioned == []
    assert rbac_seeder.seeded_tenant_ids == []
    assert audit_log.recorded == []


async def test_invalid_email_is_rejected_before_touching_any_port() -> None:
    use_case = _build()

    with pytest.raises(ValidationError):
        await use_case.execute(BootstrapTenantCommand(name="Clinica Test", admin_email="not-an-email"))


async def test_malformed_client_provided_tenant_id_is_rejected_before_touching_any_port() -> None:
    repository = _FakeTenantProvisioningRepository()
    rbac_seeder = _FakeRbacSeeder()
    audit_log = _FakeAuditLog()
    use_case = _build(repository, rbac_seeder, audit_log)

    command = BootstrapTenantCommand(
        name="Clinica Test",
        admin_email="admin@example.com",
        tenant_id="'; DROP TABLE tenants; --",
    )

    with pytest.raises(ValidationError):
        await use_case.execute(command)

    assert repository.provisioned == []
    assert rbac_seeder.seeded_tenant_ids == []
    assert audit_log.recorded == []
