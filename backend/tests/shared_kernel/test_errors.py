"""Task 3.1: `DomainError` hierarchy (design.md §2.5)."""

import pytest

from app.shared_kernel.errors import (
    ConflictError,
    DomainError,
    NotAuthorizedError,
    NotFoundError,
    ValidationError,
)


@pytest.mark.parametrize(
    "error_type",
    [NotFoundError, NotAuthorizedError, ValidationError, ConflictError],
)
def test_every_subtype_is_a_domain_error(error_type: type[DomainError]) -> None:
    assert issubclass(error_type, DomainError)


def test_domain_error_is_an_exception() -> None:
    assert issubclass(DomainError, Exception)


def test_subtypes_carry_a_message() -> None:
    err = NotFoundError("patient not found")

    assert str(err) == "patient not found"
