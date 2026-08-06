from app.modules.identity.domain.user_account import UserAccount


def _account(**overrides) -> UserAccount:
    defaults = dict(
        id="u1",
        tenant_id="t1",
        site_id="s1",
        role="reception",
        status="active",
        email="a@example.com",
        auth_subject=None,
        email_verified_at=None,
    )
    defaults.update(overrides)
    return UserAccount(**defaults)


def test_user_account_holds_every_field() -> None:
    account = _account(auth_subject="google-sub", email_verified_at="2026-01-01T00:00:00+00:00")

    assert account.id == "u1"
    assert account.tenant_id == "t1"
    assert account.site_id == "s1"
    assert account.role == "reception"
    assert account.status == "active"
    assert account.email == "a@example.com"
    assert account.auth_subject == "google-sub"
    assert account.email_verified_at == "2026-01-01T00:00:00+00:00"


def test_is_active_true_only_for_active_status() -> None:
    assert _account(status="active").is_active is True
    assert _account(status="inactive").is_active is False


def test_is_linked_to_federated_provider_reflects_auth_subject() -> None:
    assert _account(auth_subject=None).is_linked_to_federated_provider is False
    assert _account(auth_subject="google-sub").is_linked_to_federated_provider is True
