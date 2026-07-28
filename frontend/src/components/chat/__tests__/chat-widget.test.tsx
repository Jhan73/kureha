import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatWidget } from "../chat-widget";
import { useAuth } from "@/lib/auth/auth-context";
import type { AuthContextValue } from "@/lib/auth/auth-context";
import { streamChat } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/client";
import type { ChatStreamEvent } from "@/lib/api/types";

vi.mock("@/lib/auth/auth-context", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/auth/auth-context")>(
      "@/lib/auth/auth-context",
    );
  return { ...actual, useAuth: vi.fn() };
});
vi.mock("@/lib/api/chat", () => ({ streamChat: vi.fn() }));

function mockAuth(overrides: Partial<AuthContextValue> = {}) {
  vi.mocked(useAuth).mockReturnValue({
    accessToken: "access-1",
    user: { userId: "user-1", role: "patient" },
    login: vi.fn(),
    logout: vi.fn(),
    silentRefresh: vi.fn().mockResolvedValue(false),
    authorizedFetch: vi.fn(),
    ...overrides,
  });
}

function sendMessage(text: string) {
  fireEvent.change(screen.getByLabelText(/message/i), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
}

describe("ChatWidget", () => {
  beforeEach(() => {
    mockAuth();
    vi.mocked(streamChat).mockReset();
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "11111111-1111-4111-8111-111111111111",
    );
  });

  it("generates a thread id in memory via crypto.randomUUID and never persists it to any client-side storage", async () => {
    const setLocalStorage = vi.spyOn(Storage.prototype, "setItem");

    vi.mocked(streamChat).mockResolvedValueOnce(undefined);
    render(<ChatWidget />);
    sendMessage("hola");

    await waitFor(() => expect(streamChat).toHaveBeenCalled());

    expect(crypto.randomUUID).toHaveBeenCalled();
    expect(setLocalStorage).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
  });

  it("sends the trimmed message with the same in-memory thread id on every turn", async () => {
    vi.mocked(streamChat).mockResolvedValue(undefined);
    render(<ChatWidget />);

    sendMessage("  hola  ");
    await waitFor(() =>
      expect(streamChat).toHaveBeenNthCalledWith(
        1,
        expect.anything(),
        { message: "hola", clientRandomUuid: "11111111-1111-4111-8111-111111111111" },
        expect.any(Function),
      ),
    );

    sendMessage("otra vez");
    await waitFor(() =>
      expect(streamChat).toHaveBeenNthCalledWith(
        2,
        expect.anything(),
        { message: "otra vez", clientRandomUuid: "11111111-1111-4111-8111-111111111111" },
        expect.any(Function),
      ),
    );
  });

  it("does not send an empty or whitespace-only message", () => {
    render(<ChatWidget />);
    sendMessage("   ");
    expect(streamChat).not.toHaveBeenCalled();
  });

  it("shows the user message immediately and the intermediate status while Tony is working", async () => {
    let emit: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emit = onEvent;
      return new Promise(() => {});
    });

    render(<ChatWidget />);
    sendMessage("agenda una cita");

    expect(await screen.findByText("agenda una cita")).toBeInTheDocument();
    await waitFor(() => expect(emit).toBeDefined());
    emit?.({ type: "status", phase: "checking_availability", label: "Consultando disponibilidad" });

    expect(await screen.findByText("Consultando disponibilidad")).toBeInTheDocument();
  });

  it("accumulates token deltas incrementally into Tony's reply and clears status on done", async () => {
    let emit: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emit = onEvent;
    });

    render(<ChatWidget />);
    sendMessage("hola");
    await waitFor(() => expect(emit).toBeDefined());

    emit?.({ type: "status", phase: "thinking", label: "Pensando" });
    emit?.({ type: "token", delta: "Hola, " });
    emit?.({ type: "token", delta: "puedo ayudarte." });
    emit?.({
      type: "done",
      audit_ref: "aud-1",
      calendar_sync_status: null,
      finish_reason: "stop",
    });

    expect(await screen.findByText("Hola, puedo ayudarte.")).toBeInTheDocument();
    expect(screen.queryByText("Pensando")).toBeNull();
  });

  it("shows the error's user_message when the stream emits an error event, and re-enables sending", async () => {
    let emit: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emit = onEvent;
    });

    render(<ChatWidget />);
    sendMessage("sintomas raros");
    await waitFor(() => expect(emit).toBeDefined());

    emit?.({
      type: "error",
      error: {
        error_code: "clinical_scope_refused",
        category: "clinical-scope-refused",
        user_message: "Solo puedo ayudarte con temas administrativos.",
        retryable: false,
        correlation_id: "req_1",
      },
    });

    expect(
      await screen.findByText("Solo puedo ayudarte con temas administrativos."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).not.toBeDisabled();
  });

  it("shows a generic error when the initial request fails before any streaming starts", async () => {
    vi.mocked(streamChat).mockRejectedValueOnce(new ApiError(401, "Session expired"));

    render(<ChatWidget />);
    sendMessage("hola");

    expect(await screen.findByText("Session expired")).toBeInTheDocument();
  });

  it("renders Tony's Markdown response as real HTML elements (bold, link, list), not raw markdown text", async () => {
    let emit: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emit = onEvent;
    });

    render(<ChatWidget />);
    sendMessage("que horarios hay");
    await waitFor(() => expect(emit).toBeDefined());

    emit?.({
      type: "token",
      delta:
        "**Horarios disponibles:**\n\n- 10:00 con [Dr. Perez](https://example.com/dr-perez)\n- 11:00\n",
    });
    emit?.({ type: "done", audit_ref: "aud-1", calendar_sync_status: null, finish_reason: "stop" });

    const bold = await screen.findByText("Horarios disponibles:");
    expect(bold.tagName).toBe("STRONG");

    const link = screen.getByRole("link", { name: "Dr. Perez" });
    expect(link).toHaveAttribute("href", "https://example.com/dr-perez");

    const secondItem = screen.getByText("11:00");
    expect(secondItem.tagName).toBe("LI");
    expect(secondItem.closest("ul")).not.toBeNull();
  });

  it("neutralizes malicious markup in Tony's response: a javascript: link loses its href, and a raw script tag never becomes an executable element", async () => {
    let emit: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emit = onEvent;
    });

    render(<ChatWidget />);
    sendMessage("hola");
    await waitFor(() => expect(emit).toBeDefined());

    emit?.({
      type: "token",
      delta:
        "[click here](javascript:window.__pwned=true) Hola <script>window.__pwned = true;</script> hay turnos.",
    });
    emit?.({ type: "done", audit_ref: "aud-1", calendar_sync_status: null, finish_reason: "stop" });

    // The javascript: URI is the load-bearing assertion: it only gets stripped
    // once react-markdown's output is actually passed through rehype-sanitize's
    // href-protocol allowlist -- it is NOT stripped by react-markdown alone.
    const link = await screen.findByText("click here");
    expect(link.tagName).toBe("A");
    // rehype-sanitize's default schema disallows the javascript: protocol on
    // href, so the whole attribute is stripped rather than left neutered.
    expect(link.getAttribute("href")).toBeNull();

    // Defense-in-depth: the raw <script> tag must never become a real DOM
    // script element or execute, regardless of renderer.
    expect(document.querySelector("script")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  // tasks.md 14.5: a confirmation prompt (turn N asks, turn N+1
  // affirms/declines) is deliberately NOT a special UI mode -- design.md
  // §8.5 states it "travels... with no protocol difference from a normal
  // response" and spec `embedded-patient-chat`'s "Confirmation Required
  // Before Any Mutating Action" scenarios never describe a distinct
  // confirm/decline widget, only that the prompt is delivered in-stream and
  // the next turn's plain-text reply resolves it. These are approval tests
  // (strict-tdd.md's "Approval Testing" pattern): they capture and prove
  // CURRENT behavior of the existing turn-N/turn-N+1 send path rather than
  // drive new production code -- 14.3/14.4 already built the only mechanism
  // this needs (an ordinary assistant turn, an ordinary user turn, the same
  // streamChat() call). No implementation changes accompany this task.
  it("renders a confirmation prompt as an ordinary assistant turn, then the user's plain-text affirmation on the next turn through the exact same send path", async () => {
    let emitTurnN: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emitTurnN = onEvent;
    });

    render(<ChatWidget />);
    sendMessage("agenda un turno con la Dra. X el martes a las 10");
    await waitFor(() => expect(emitTurnN).toBeDefined());

    emitTurnN?.({
      type: "token",
      delta: "Voy a reservar cita con la Dra. X el martes a las 10:00. ¿Confirmas?",
    });
    emitTurnN?.({ type: "done", audit_ref: null, calendar_sync_status: null, finish_reason: "stop" });

    expect(
      await screen.findByText("Voy a reservar cita con la Dra. X el martes a las 10:00. ¿Confirmas?"),
    ).toBeInTheDocument();

    // No dedicated confirm/decline affordance exists -- the send form is the
    // only way to respond, same as any other turn.
    expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /decline/i })).toBeNull();
    expect(screen.getByRole("button", { name: /send/i })).not.toBeDisabled();

    let emitTurnNPlus1: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emitTurnNPlus1 = onEvent;
    });

    sendMessage("Sí, confirmo");

    // Same call shape as any other turn: same clientRandomUuid (thread
    // continuity), a plain message string, no confirmation-specific field.
    await waitFor(() =>
      expect(streamChat).toHaveBeenNthCalledWith(
        2,
        expect.anything(),
        { message: "Sí, confirmo", clientRandomUuid: "11111111-1111-4111-8111-111111111111" },
        expect.any(Function),
      ),
    );
    await waitFor(() => expect(emitTurnNPlus1).toBeDefined());

    expect(await screen.findByText("Sí, confirmo")).toBeInTheDocument();

    emitTurnNPlus1?.({
      type: "token",
      delta: "Listo, tu cita con la Dra. X quedó confirmada para el martes a las 10:00.",
    });
    emitTurnNPlus1?.({ type: "done", audit_ref: "aud-2", calendar_sync_status: "ok", finish_reason: "stop" });

    expect(
      await screen.findByText("Listo, tu cita con la Dra. X quedó confirmada para el martes a las 10:00."),
    ).toBeInTheDocument();
    // Turn N's original prompt is still visible, untouched by turn N+1.
    expect(
      screen.getByText("Voy a reservar cita con la Dra. X el martes a las 10:00. ¿Confirmas?"),
    ).toBeInTheDocument();
  });

  it("also renders a decline exchange as ordinary chat turns, reusing the identical send path with no appointment-specific branching", async () => {
    let emitTurnN: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emitTurnN = onEvent;
    });

    render(<ChatWidget />);
    sendMessage("cancela mi proxima cita");
    await waitFor(() => expect(emitTurnN).toBeDefined());

    emitTurnN?.({
      type: "token",
      delta: "Voy a cancelar tu cita del jueves a las 9:00. ¿Confirmas?",
    });
    emitTurnN?.({ type: "done", audit_ref: null, calendar_sync_status: null, finish_reason: "stop" });

    expect(
      await screen.findByText("Voy a cancelar tu cita del jueves a las 9:00. ¿Confirmas?"),
    ).toBeInTheDocument();

    let emitTurnNPlus1: ((event: ChatStreamEvent) => void) | undefined;
    vi.mocked(streamChat).mockImplementationOnce(async (_fetch, _params, onEvent) => {
      emitTurnNPlus1 = onEvent;
    });

    sendMessage("No, dejalo");

    await waitFor(() =>
      expect(streamChat).toHaveBeenNthCalledWith(
        2,
        expect.anything(),
        { message: "No, dejalo", clientRandomUuid: "11111111-1111-4111-8111-111111111111" },
        expect.any(Function),
      ),
    );
    await waitFor(() => expect(emitTurnNPlus1).toBeDefined());

    emitTurnNPlus1?.({
      type: "token",
      delta: "Entendido, no se realizó ningún cambio. ¿En qué más puedo ayudarte?",
    });
    emitTurnNPlus1?.({ type: "done", audit_ref: null, calendar_sync_status: null, finish_reason: "stop" });

    expect(await screen.findByText("No, dejalo")).toBeInTheDocument();
    expect(
      await screen.findByText("Entendido, no se realizó ningún cambio. ¿En qué más puedo ayudarte?"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).not.toBeDisabled();
  });
});
