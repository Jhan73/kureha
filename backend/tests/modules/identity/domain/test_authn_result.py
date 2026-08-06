from app.modules.identity.domain.authn_result import AuthnResult


def test_authn_result_holds_the_four_authn_only_fields() -> None:
    result = AuthnResult(subject="idp-sub-1", email="a@example.com", email_verified=True, provider="password")

    assert result.subject == "idp-sub-1"
    assert result.email == "a@example.com"
    assert result.email_verified is True
    assert result.provider == "password"


def test_authn_result_is_immutable() -> None:
    result = AuthnResult(subject="s", email="e@example.com", email_verified=False, provider="google")

    try:
        result.email = "other@example.com"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("AuthnResult must be frozen")
