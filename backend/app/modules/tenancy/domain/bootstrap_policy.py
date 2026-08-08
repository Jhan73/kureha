import re
import uuid

from app.shared_kernel.errors import ValidationError

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_SITE_SUFFIX = "Main Site"


class BootstrapPolicy:
    @staticmethod
    def validate_name(name: str) -> None:
        if not name or not name.strip():
            raise ValidationError("tenant name must not be empty")

    @staticmethod
    def validate_admin_email(email: str) -> None:
        if not email or not _EMAIL_PATTERN.match(email):
            raise ValidationError(f"invalid admin email: {email!r}")

    @staticmethod
    def validate_tenant_id(tenant_id: str) -> None:
        try:
            uuid.UUID(tenant_id)
        except ValueError as exc:
            raise ValidationError(f"invalid tenant_id: {tenant_id!r}") from exc

    @staticmethod
    def resolve_site_name(tenant_name: str, site_name: str | None) -> str:
        if site_name and site_name.strip():
            return site_name.strip()
        return f"{tenant_name.strip()} {_DEFAULT_SITE_SUFFIX}"
