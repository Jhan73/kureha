from app.modules.identity.adapters.outbound.tokens.jwt_constants import DEFAULT_ALGORITHM
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_verifier import JwtAccessTokenVerifier


def test_default_algorithm_is_hs256() -> None:
    assert DEFAULT_ALGORITHM == "HS256"


def test_issuer_and_verifier_share_the_same_default_algorithm_source(monkeypatch) -> None:
    import app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer as issuer_mod
    import app.modules.identity.adapters.outbound.tokens.jwt_access_token_verifier as verifier_mod

    assert issuer_mod.DEFAULT_ALGORITHM is DEFAULT_ALGORITHM
    assert verifier_mod.DEFAULT_ALGORITHM is DEFAULT_ALGORITHM

    class _FakeClock:
        def now(self):
            from datetime import datetime, timezone

            return datetime(2026, 1, 1, tzinfo=timezone.utc)

    issuer = JwtAccessTokenIssuer(secret="s", clock=_FakeClock())
    verifier = JwtAccessTokenVerifier(secret="s")
    assert issuer._algorithm == DEFAULT_ALGORITHM
    assert verifier._algorithm == DEFAULT_ALGORITHM
