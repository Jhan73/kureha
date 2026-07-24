"""LangGraph orchestration core (design.md §8): `KurehaState`, graph nodes,
edges, and `build_graph()`. Platform code -- orchestrates across business
modules by calling their public use cases (backend/AGENTS.md); nothing
inside `app.modules.*` may import from here."""
