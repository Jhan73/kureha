import { describe, expect, it, vi } from "vitest";
import { streamChat } from "../chat";
import { ApiError } from "../client";
import type { ChatStreamEvent } from "../types";

/** Emits chunks one at a time to exercise frame-boundary buffering. */
function sseResponse(status: number, chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, { status });
}

describe("streamChat", () => {
  it("posts the message and client_random_uuid to /chat/stream", async () => {
    const authorizedFetch = vi.fn().mockResolvedValueOnce(sseResponse(200, []));

    await streamChat(
      authorizedFetch,
      { message: "hola", clientRandomUuid: "uuid-1" },
      () => {},
    );

    expect(authorizedFetch).toHaveBeenCalledWith(
      "/chat/stream",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({ message: "hola", client_random_uuid: "uuid-1" }),
      }),
    );
  });

  it("parses status, token, and done events in order, even when a single frame arrives split across chunks", async () => {
    const frame1 = 'event: status\ndata: {"phase":"checking_availability","label":"Consultando disponibilidad"}\n\n';
    const frame2 = 'event: token\ndata: {"delta":"Tengo estos horarios "}\n\n';
    const frame3 =
      'event: done\ndata: {"audit_ref":"aud-1","calendar_sync_status":"ok","finish_reason":"stop"}\n\n';
    const splitIndex = Math.floor(frame2.length / 2);
    const authorizedFetch = vi.fn().mockResolvedValueOnce(
      sseResponse(200, [
        frame1,
        frame2.slice(0, splitIndex),
        frame2.slice(splitIndex),
        frame3,
      ]),
    );

    const events: ChatStreamEvent[] = [];
    await streamChat(
      authorizedFetch,
      { message: "hola", clientRandomUuid: "uuid-1" },
      (event) => events.push(event),
    );

    expect(events).toEqual([
      { type: "status", phase: "checking_availability", label: "Consultando disponibilidad" },
      { type: "token", delta: "Tengo estos horarios " },
      { type: "done", audit_ref: "aud-1", calendar_sync_status: "ok", finish_reason: "stop" },
    ]);
  });

  it("parses an error event without throwing -- the stream itself is the delivery channel", async () => {
    const frame =
      'event: error\ndata: {"error_code":"clinical_scope_refused","category":"clinical-scope-refused","user_message":"Solo puedo ayudarte con temas administrativos.","retryable":false,"correlation_id":"req_1"}\n\n';
    const authorizedFetch = vi.fn().mockResolvedValueOnce(sseResponse(200, [frame]));

    const events: ChatStreamEvent[] = [];
    await streamChat(
      authorizedFetch,
      { message: "sintomas", clientRandomUuid: "uuid-1" },
      (event) => events.push(event),
    );

    expect(events).toEqual([
      {
        type: "error",
        error: {
          error_code: "clinical_scope_refused",
          category: "clinical-scope-refused",
          user_message: "Solo puedo ayudarte con temas administrativos.",
          retryable: false,
          correlation_id: "req_1",
        },
      },
    ]);
  });

  it("throws an ApiError when the initial request itself fails (e.g. auth rejected before the stream starts)", async () => {
    const authorizedFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ user_message: "Session expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      streamChat(authorizedFetch, { message: "hola", clientRandomUuid: "uuid-1" }, () => {}),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
