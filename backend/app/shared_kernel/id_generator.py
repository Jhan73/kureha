import uuid
from typing import Protocol


class IdGeneratorPort(Protocol):
    def new_id(self) -> str: ...


class UuidGenerator:
    def new_id(self) -> str:
        return str(uuid.uuid4())
