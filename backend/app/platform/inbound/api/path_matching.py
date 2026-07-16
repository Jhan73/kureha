"""Shared path-prefix matching helper, deduplicated out of
`AccessControlMiddleware._is_exempt` and `AuthRateLimitMiddleware._is_protected`
(both middlewares previously carried their own identical
`path == prefix or path.startswith(prefix)` implementation)."""


def matches_any_prefix(path: str, prefixes: frozenset[str]) -> bool:
    """Returns `True` if `path` starts with ANY of `prefixes`.

    **This is substring-prefix matching, not segment-boundary matching** --
    a prefix like `/auth/login` also matches `/auth/login-audit-export`
    (there is no implicit `/` or word-boundary check after the prefix).
    Callers configuring `exempt_path_prefixes`/`protected_path_prefixes`
    must choose prefixes carefully: include a trailing `/` for
    directory-like exemptions (e.g. `/public/`), or use the full,
    unambiguous path string for a single route (e.g. `/auth/login` with no
    intent to also match sibling routes)."""
    return any(path.startswith(prefix) for prefix in prefixes)
