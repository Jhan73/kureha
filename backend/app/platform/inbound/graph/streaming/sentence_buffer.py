"""`SentenceBoundaryBuffer` (design.md §8.7, tasks.md task 12.4): the
sentence-boundary chunk-buffering algorithm design.md's `response_guard`
section describes verbatim -- "los tokens del agente se acumulan en un
buffer hasta el primer limite de oracion (`\\n`, `.`, `?`, `!`) o hasta ~80
tokens si no hay limite en ese tramo -- lo que ocurra primero".

**"Tokens" here means whitespace-separated words, a deliberate, flagged
approximation of true LLM subword tokens.** This codebase has no tokenizer
dependency anywhere (every LLM adapter calls `ChatAnthropic` through
`langchain-anthropic`, which does not expose a standalone tokenizer this
buffer could reuse without adding a new dependency for a soft, UX-latency
fallback threshold, not a hard security boundary). A word-count
approximation is close enough for the fallback's actual purpose (bound how
long a client waits without a boundary ever appearing, e.g. a long
comma-only sentence) -- flagged here rather than silently presented as exact
token counting.

**Boundary detection splits AT the boundary character, not around the whole
delta.** A delta containing "Hola. Como estas" must flush "Hola." as one
complete unit and keep "Como estas" buffered for the NEXT unit -- collapsing
the entire delta into one flush (or discarding the remainder) would either
merge two sentences into one guard-classification unit or silently drop
text."""

_BOUNDARY_CHARS = frozenset({"\n", ".", "?", "!"})


class SentenceBoundaryBuffer:
    def __init__(self, *, token_fallback: int = 80) -> None:
        self._token_fallback = token_fallback
        self._buf: list[str] = []
        self._word_count = 0

    def push(self, delta: str) -> list[str]:
        """Feeds one token delta; returns zero or more completed units (a
        single delta could contain more than one boundary character, e.g. a
        very large delta -- rare in practice but handled correctly, not
        just for the common one-boundary-per-delta case)."""
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
        """Drains whatever is left in the buffer (no boundary, below the
        fallback threshold) -- called once the upstream text source is
        exhausted, so no trailing partial sentence is ever silently
        dropped."""
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
