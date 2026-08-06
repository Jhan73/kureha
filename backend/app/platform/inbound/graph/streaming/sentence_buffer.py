_BOUNDARY_CHARS = frozenset({"\n", ".", "?", "!"})


class SentenceBoundaryBuffer:
    def __init__(self, *, token_fallback: int = 80) -> None:
        self._token_fallback = token_fallback
        self._buf: list[str] = []
        self._word_count = 0

    def push(self, delta: str) -> list[str]:
        """Append a delta; return any completed sentence units."""
        units: list[str] = []
        remaining = delta
        while remaining:
            boundary_index = next((i for i, ch in enumerate(remaining) if ch in _BOUNDARY_CHARS), None)
            if boundary_index is None:
                break
            head, remaining = remaining[: boundary_index + 1], remaining[boundary_index + 1 :]
            self._append(head)
            units.append("".join(self._buf))
            self._reset()

        if remaining:
            self._append(remaining)

        if self._buf and self._word_count >= self._token_fallback:
            units.append("".join(self._buf))
            self._reset()

        return units

    def flush(self) -> str | None:
        """Drain remaining buffer (no trailing partial dropped)."""
        if not self._buf:
            return None
        unit = "".join(self._buf)
        self._reset()
        return unit

    def _append(self, text: str) -> None:
        self._buf.append(text)
        self._word_count += len(text.split())

    def _reset(self) -> None:
        self._buf = []
        self._word_count = 0
