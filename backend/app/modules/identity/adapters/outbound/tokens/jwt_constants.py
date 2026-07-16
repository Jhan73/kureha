"""Shared JWT signing constants, deduplicated out of
`jwt_access_token_issuer.py`/`jwt_access_token_verifier.py` (both
previously declared their own private `_ALGORITHM = "HS256"`)."""

DEFAULT_ALGORITHM = "HS256"
