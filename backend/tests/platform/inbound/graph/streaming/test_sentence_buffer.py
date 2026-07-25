"""`SentenceBoundaryBuffer` (design.md §8.7, tasks.md task 12.4): accumulates
token deltas until a sentence boundary (`\\n`, `.`, `?`, `!`) or a ~80-token
fallback -- whichever occurs first -- design.md's own algorithm, verbatim:
"los tokens del agente se acumulan en un buffer hasta el primer limite de
oracion... o hasta ~80 tokens si no hay limite en ese tramo -- lo que ocurra
primero"."""

from app.platform.inbound.graph.streaming.sentence_buffer import SentenceBoundaryBuffer


def test_push_returns_no_unit_before_a_boundary_is_reached() -> None:
    buf = SentenceBoundaryBuffer()

    units = buf.push("Tengo estos horarios ")

    assert units == []


def test_push_flushes_a_unit_on_a_period() -> None:
    buf = SentenceBoundaryBuffer()

    buf.push("Tengo un horario libre")
    units = buf.push(" el martes a las 10.")

    # the completed unit includes everything buffered ACROSS both push()
    # calls, up to and including the boundary.
    assert units == ["Tengo un horario libre el martes a las 10."]
    assert buf.flush() is None


def test_a_delta_spanning_a_boundary_splits_the_remainder_into_the_next_unit() -> None:
    buf = SentenceBoundaryBuffer()

    units = buf.push("Hola. Como estas")

    assert units == ["Hola."]
    # "Como estas" (the remainder after the boundary, WITH its leading
    # space) stays buffered for the NEXT unit, not lost or re-emitted with
    # the first.
    assert buf.flush() == " Como estas"


def test_multiple_boundaries_in_one_delta_yield_multiple_units() -> None:
    buf = SentenceBoundaryBuffer()

    units = buf.push("Hola. Bien? Genial!")

    assert units == ["Hola.", " Bien?", " Genial!"]


def test_word_count_fallback_flushes_after_the_configured_threshold_with_no_boundary() -> None:
    buf = SentenceBoundaryBuffer(token_fallback=3)

    units = buf.push("one two three")

    assert units == ["one two three"]


def test_word_count_fallback_does_not_fire_before_the_threshold() -> None:
    buf = SentenceBoundaryBuffer(token_fallback=5)

    units = buf.push("one two")

    assert units == []
    assert buf.flush() == "one two"


def test_flush_returns_none_when_buffer_is_empty() -> None:
    buf = SentenceBoundaryBuffer()

    assert buf.flush() is None


def test_flush_drains_and_resets_the_buffer() -> None:
    buf = SentenceBoundaryBuffer()
    buf.push("no boundary here")

    first = buf.flush()
    second = buf.flush()

    assert first == "no boundary here"
    assert second is None


def test_boundary_after_a_fallback_flush_starts_a_fresh_word_count() -> None:
    """Regression guard: the word-count accumulator must reset on EVERY
    flush (boundary-triggered or fallback-triggered), never silently keep
    counting from a stale total."""
    buf = SentenceBoundaryBuffer(token_fallback=3)

    first_units = buf.push("one two three")  # fallback fires, resets counter
    second_units = buf.push(" four.")  # only 1 word since reset -- boundary, not fallback

    assert first_units == ["one two three"]
    assert second_units == [" four."]
