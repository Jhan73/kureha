"""`matches_any_prefix` -- the shared prefix-matching helper deduplicated
out of `AccessControlMiddleware._is_exempt` and
`AuthRateLimitMiddleware._is_protected` (both did `path == prefix or
path.startswith(prefix)`, which is redundant: `startswith` already covers
exact equality)."""

from app.platform.inbound.api.path_matching import matches_any_prefix


def test_no_prefixes_never_matches() -> None:
    assert matches_any_prefix("/auth/login", frozenset()) is False


def test_exact_path_equal_to_a_prefix_matches() -> None:
    assert matches_any_prefix("/auth/login", frozenset({"/auth/login"})) is True


def test_path_starting_with_a_prefix_matches() -> None:
    assert matches_any_prefix("/auth/login/callback", frozenset({"/auth/login"})) is True


def test_unrelated_path_does_not_match() -> None:
    assert matches_any_prefix("/appointments", frozenset({"/auth/login"})) is False


def test_substring_prefix_matching_is_not_segment_aware() -> None:
    """Documented gotcha: `/auth/login` also matches
    `/auth/login-audit-export` -- callers must choose prefixes carefully."""
    assert matches_any_prefix("/auth/login-audit-export", frozenset({"/auth/login"})) is True


def test_matches_when_any_of_multiple_prefixes_matches() -> None:
    prefixes = frozenset({"/auth/login", "/auth/refresh"})
    assert matches_any_prefix("/auth/refresh", prefixes) is True
