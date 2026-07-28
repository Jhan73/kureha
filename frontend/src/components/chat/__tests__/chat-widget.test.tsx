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
});
