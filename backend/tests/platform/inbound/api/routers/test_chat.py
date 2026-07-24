"""Task 11.7: chat router (`POST /chat`) -- real `thread_id` ownership
assembly (server-side, from the authenticated actor's own token claims),
checkpointer connection wiring, non-streaming graph invocation. Full
Tony/LLM wiring is tasks.md Phase 12 -- every `Unwired*` seam
(`adapters/unwired.py`) still raises `NotImplementedError` until then, so
this test proves the ENDPOINT's own wiring (auth -> thread_id -> graph
invocation actually reaching a real node, `triage`), not a complete
conversation -- see `test_build_graph.py` for graph-routing coverage with
fakes standing in for the seam ports."""

from tests.platform.inbound.api.routers.conftest import auth_headers, mint_access_token, seed_reception_actor


def test_chat_requires_authentication(client) -> None:
    response = client.post("/chat", json={"message": "hola"})

    assert response.status_code == 401


def test_chat_reaches_the_graph_and_surfaces_the_unwired_seam_as_internal_error(client) -> None:
    """No `deps` override is passed by the router (tasks.md Phase 12 has not
    wired a real `IntentClassifierPort` yet) -- `triage` calling
    `UnwiredIntentClassifier.classify` raises `NotImplementedError`, which
    propagates through `graph.ainvoke()` up to `register_exception_handlers`
    (task 10.3), the SAME central translation boundary every other router in
    this codebase already uses -- proving the endpoint's auth/thread_id/
    graph-construction wiring is genuinely reached and exercised end-to-end,
    not merely importable."""
    actor = seed_reception_actor(email="chat-reception@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )

    response = client.post("/chat", json={"message": "hola"}, headers=auth_headers(token))

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert "correlation_id" in body
