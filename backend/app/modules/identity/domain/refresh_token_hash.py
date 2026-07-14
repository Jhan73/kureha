"""`hash_refresh_token`: the one-way transform applied to an opaque refresh
secret before it is ever persisted (design.md §17.4, spec `user-authentication`
-> "No Plaintext Credential Storage in Kureha"). SHA-256 is sufficient here
(unlike a password hash) because the input is already a high-entropy,
cryptographically random secret (`SecretGeneratorPort.generate()`), not a
low-entropy user-chosen password -- no salting/adaptive-cost hashing (bcrypt/
argon2) is needed to resist brute force against a 256-bit random value."""

import hashlib


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
