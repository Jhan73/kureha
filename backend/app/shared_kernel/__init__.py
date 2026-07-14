"""Shared kernel: `TenantContext`, `DomainError` hierarchy,
`ClockPort`/`SystemClock`, `IdGeneratorPort`/`UuidGenerator` (design.md
§2.5). Pure value objects and trivial ports only -- no IO, no business
logic, no dependency on any module."""
