from app.modules.identity.domain.refresh_token_hash import hash_refresh_token


def test_same_input_always_hashes_the_same() -> None:
    assert hash_refresh_token("secret-1") == hash_refresh_token("secret-1")


def test_different_input_hashes_differently() -> None:
    assert hash_refresh_token("secret-1") != hash_refresh_token("secret-2")


def test_hash_never_equals_the_plaintext() -> None:
    plaintext = "super-secret-refresh-token"
    assert hash_refresh_token(plaintext) != plaintext
