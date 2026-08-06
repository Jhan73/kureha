from app.modules.identity.adapters.outbound.tokens.secure_secret_generator import SecureSecretGenerator


def test_generate_returns_a_non_empty_string() -> None:
    generator = SecureSecretGenerator()
    value = generator.generate()
    assert isinstance(value, str)
    assert len(value) >= 32


def test_generate_returns_unique_values() -> None:
    generator = SecureSecretGenerator()
    values = {generator.generate() for _ in range(50)}
    assert len(values) == 50
