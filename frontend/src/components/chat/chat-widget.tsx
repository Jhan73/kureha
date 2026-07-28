"use client";

import { useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth/auth-context";
import { streamChat } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/client";
import type { ChatStreamEvent } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
}

/**
 * Embedded patient chat (tasks.md 14.3, design.md §8.5/§8.6, spec
 * `embedded-patient-chat`). Talks to `POST /chat/stream` via `streamChat`
 * (`lib/api/chat.ts`) -- SSE consumed through `fetch` + `ReadableStream`,
 * never the native `EventSource` (GET-only, can't carry the message body).
 *
 * **`thread_id` -- in-memory only, per spec's own hard requirement ("Thread
 * ID is never persisted client-side").** Generated exactly once via
 * `useState(() => crypto.randomUUID())`, the same lazy-initializer shape
 * design.md §8.6 itself shows -- never written to `localStorage`,
 * `sessionStorage`, cookies, or IndexedDB, and never read back from any of
 * them either. A page reload unmounts this component, the in-memory value
 * is lost, and remounting generates a brand-new one -- by construction, not
 * by an explicit "clear on unload" handler (design.md §8.6's own "Refresh =
 * nueva conversacion" argument). Sent to the backend as the request body's
 * `client_random_uuid` field (`chat.py`'s `ChatRequest` -- the real,
 * tenant/user-scoped `thread_id` is assembled server-side FROM this value
 * plus the caller's authenticated identity, never trusted as-is).
 *
 * **Rendering is plain text (`whitespace-pre-wrap`), a deliberate,
 * explicitly out-of-scope placeholder.** tasks.md 14.4
 * (`react-markdown`+`rehype-sanitize`) is NOT implemented here -- Tony's
 * replies render as literal text, no Markdown parsing. Likewise, the
 * turn-N/turn-N+1 confirmation-prompt UX (tasks.md 14.5) is not
 * special-cased here: a confirmation prompt from Tony arrives as an
 * ordinary assistant turn (design.md §8.5's own "sin ninguna diferencia de
 * protocolo respecto a una respuesta normal"), so no additional handling is
 * needed for THIS task to already display it.
 */

export function ChatWidget() {
  const { authorizedFetch } = useAuth();
  const [threadId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [draftText, setDraftText] = useState("");
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const draftRef = useRef("");
  const turnIdRef = useRef(0);

  function nextTurnId(): string {
    turnIdRef.current += 1;
    return `turn-${turnIdRef.current}`;
  }

  function finalizeDraft() {
    setStatusLabel(null);
    if (draftRef.current) {
      const text = draftRef.current;
      setMessages((prev) => [...prev, { id: nextTurnId(), role: "assistant", text }]);
    }
    draftRef.current = "";
    setDraftText("");
  }

  function handleStreamEvent(event: ChatStreamEvent) {
    switch (event.type) {
      case "status":
        setStatusLabel(event.label);
        break;
      case "token":
        draftRef.current += event.delta;
        setDraftText(draftRef.current);
        break;
      case "done":
        finalizeDraft();
        break;
      case "error":
        finalizeDraft();
        setErrorMessage(event.error.user_message);
        break;
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || sending) {
      return;
    }

    setErrorMessage(null);
    setMessages((prev) => [...prev, { id: nextTurnId(), role: "user", text: trimmed }]);
    setInput("");
    setSending(true);
    setStatusLabel(null);
    draftRef.current = "";
    setDraftText("");

    try {
      await streamChat(
        authorizedFetch,
        { message: trimmed, clientRandomUuid: threadId },
        handleStreamEvent,
      );
    } catch (err) {
      finalizeDraft();
      setErrorMessage(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    } finally {
      setSending(false);
      setStatusLabel(null);
    }
  }

  return (
    <Card className="flex w-full max-w-lg flex-1 flex-col">
      <CardHeader>
        <CardTitle>Chat with Tony</CardTitle>
        <CardDescription>
          Ask about scheduling, rescheduling, or reminders. Tony recommends and
          orients administratively, but never diagnoses.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        {errorMessage ? (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        ) : null}
        <ul className="flex flex-1 flex-col gap-2" aria-label="Conversation">
          {messages.map((turn) => (
            <li
              key={turn.id}
              className={turn.role === "user" ? "self-end text-right" : "self-start"}
            >
              <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm">
                {turn.text}
              </p>
            </li>
          ))}
          {draftText ? (
            <li className="self-start">
              <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm">
                {draftText}
              </p>
            </li>
          ) : null}
        </ul>
        {statusLabel ? (
          <p role="status" className="text-sm text-muted-foreground">
            {statusLabel}
          </p>
        ) : null}
      </CardContent>
      <CardFooter>
        <form onSubmit={handleSend} className="flex w-full items-end gap-2" noValidate>
          <div className="flex-1">
            <Label htmlFor="chat-message" className="sr-only">
              Message
            </Label>
            <Input
              id="chat-message"
              name="chat-message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              disabled={sending}
              autoComplete="off"
            />
          </div>
          <Button type="submit" disabled={sending}>
            {sending ? "Sending..." : "Send"}
          </Button>
        </form>
      </CardFooter>
    </Card>
  );
}
