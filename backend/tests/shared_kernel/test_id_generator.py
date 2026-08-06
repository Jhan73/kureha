import uuid

from app.shared_kernel.id_generator import UuidGenerator


def test_uuid_generator_returns_a_valid_uuid_string() -> None:
    generated = UuidGenerator().new_id()

    assert uuid.UUID(generated) is not None


def test_uuid_generator_returns_unique_ids() -> None:
    generator = UuidGenerator()

    assert generator.new_id() != generator.new_id()
