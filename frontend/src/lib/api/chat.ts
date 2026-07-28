import { ApiError, type AuthorizedFetch } from "./client";
import type { ChatStreamEvent } from "./types";

/**
 * `POST /chat/stream` consumer (design.md §8.5, tasks.md task 14.3):
 * `fetch` + `ReadableStream`, NOT the native `EventSource` -- `EventSource`
 * is GET-only and cannot carry the message body, per design.md's own note.
 * Goes through the caller-supplied `authorizedFetch` (see
 * `lib/auth/auth-context.tsx`) so the bearer token and single-retry-on-401
 * flow are reused unchanged, same as `scheduling.ts`.
 */
export interface StreamChatParams {
  message: string;
  clientRandomUuid: string;
}

/**
 * Reads the response body incrementally and invokes `onEvent` once per
 * fully-received SSE frame, in arrival order. Resolves once the server
 * closes the stream (a `done` or `error` event, per design.md §21, is
 * always the LAST frame the backend sends -- this function does not treat
 * an `error` frame as a throw, since the SSE channel itself is the delivery
 * mechanism for that error, not an HTTP failure).
 *
 * Throws `ApiError` only when the INITIAL request fails before any
 * streaming begins (e.g. the access token was rejected and the
 * refresh-retry in `authorizedFetch` also failed) -- see `chat.py`'s
 * `chat_stream()`: once the `StreamingResponse` starts, HTTP status is
 * already committed to 200 and every subsequent failure is surfaced as an
 * `error` SSE event instead.
 */
export async function streamChat(
  authorizedFetch: AuthorizedFetch,
  params: StreamChatParams,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  const response = await authorizedFetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: params.message,
      client_random_uuid: params.clientRandomUuid,
    }),
  });

  if (!response.ok || !response.body) {
    let message = response.statusText || "Chat stream request failed";
    try {
      const body = await response.json();
      message = body?.user_message ?? body?.detail ?? message;
    } catch {
      // Body wasn't JSON (or was empty) -- fall back to statusText.
    }
    throw new ApiError(response.status, message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
    }

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = parseSseFrame(frame);
      if (event) {
        onEvent(event);
      }
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      return;
    }
  }
}

/**
 * Parses ONE `event: {type}\ndata: {json}` frame (the exact shape
 * `format_sse_event` writes server-side, `backend/app/platform/inbound/
 * graph/streaming/sse.py`) into a typed `ChatStreamEvent`. Returns `null`
 * for a malformed or unrecognized frame rather than throwing -- a single
 * unparsable frame should not abort an otherwise-healthy stream.
 */
function parseSseFrame(frame: string): ChatStreamEvent | null {
  let eventType: string | null = null;
  let data: string | null = null;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      eventType = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data = line.slice("data:".length).trim();
    }
  }
  if (!eventType || data === null) {
    return null;
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }

  switch (eventType) {
    case "status":
      return { type: "status", phase: String(payload.phase), label: String(payload.label) };
    case "token":
      return { type: "token", delta: String(payload.delta) };
    case "done":
      return {
        type: "done",
        audit_ref: (payload.audit_ref as string | null) ?? null,
        calendar_sync_status: (payload.calendar_sync_status as string | null) ?? null,
        finish_reason: (payload.finish_reason as string | null) ?? null,
      };
    case "error":
      return {
        type: "error",
        error: {
          error_code: String(payload.error_code),
          category: String(payload.category),
          user_message: String(payload.user_message),
          retryable: Boolean(payload.retryable),
          correlation_id: String(payload.correlation_id),
        },
      };
    default:
      return null;
  }
}
