import pytest

from app.modules.tenancy.domain.bootstrap_policy import BootstrapPolicy
from app.shared_kernel.errors import ValidationError


def test_empty_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BootstrapPolicy.validate_name("")


def test_blank_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BootstrapPolicy.validate_name("   ")


def test_non_empty_name_is_accepted() -> None:
    BootstrapPolicy.validate_name("Clinica Test")


def test_email_without_at_sign_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BootstrapPolicy.validate_admin_email("not-an-email")


def test_email_without_domain_dot_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BootstrapPolicy.validate_admin_email("admin@localhost")


def test_valid_email_is_accepted() -> None:
    BootstrapPolicy.validate_admin_email("admin@example.com")


def test_site_name_defaults_from_tenant_name_when_not_provided() -> None:
    assert BootstrapPolicy.resolve_site_name("Clinica Test", None) == "Clinica Test Main Site"


def test_site_name_defaults_from_tenant_name_when_blank() -> None:
    assert BootstrapPolicy.resolve_site_name("Clinica Test", "   ") == "Clinica Test Main Site"


def test_provided_site_name_is_used_when_present() -> None:
    assert BootstrapPolicy.resolve_site_name("Clinica Test", "Sede Norte") == "Sede Norte"
