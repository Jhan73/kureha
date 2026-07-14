"""`IdGeneratorPort`: the only sanctioned way to mint a new domain id
(design.md §2.5). Every table's primary key already defaults to
`gen_random_uuid()` at the DB layer (design.md §4.1) -- this port exists for
the cases where application code needs an id *before* the INSERT happens
(e.g. deriving a value that must be known ahead of a write, or generating an
id for a non-persisted value object), so tests can supply a deterministic
fake instead of asserting against a random UUID.
"""

import uuid
from typing import Protocol


class IdGeneratorPort(Protocol):
    def new_id(self) -> str:
        """Returns a new globally-unique id as its string representation."""
        ...


class UuidGenerator:
    """The only production implementation -- trivial enough that, per
    design.md §2.5, it does not warrant its own module."""

    def new_id(self) -> str:
        return str(uuid.uuid4())
