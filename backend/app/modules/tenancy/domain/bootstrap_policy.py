import re

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
    def resolve_site_name(tenant_name: str, site_name: str | None) -> str:
        if site_name and site_name.strip():
            return site_name.strip()
        return f"{tenant_name.strip()} {_DEFAULT_SITE_SUFFIX}"
