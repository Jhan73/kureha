import { ApiError, type AuthorizedFetch } from "./client";
import type { ChatStreamEvent } from "./types";

export interface StreamChatParams {
  message: string;
  clientRandomUuid: string;
}

/** POST SSE via fetch (EventSource is GET-only); mid-stream failures arrive as `error` frames. */
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

/** Returns null for a bad frame so one corrupt frame never aborts the stream. */
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
