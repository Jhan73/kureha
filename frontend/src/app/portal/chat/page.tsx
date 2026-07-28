"use client";

import { RequireAuth } from "@/lib/auth/require-auth";
import { ChatWidget } from "@/components/chat/chat-widget";

// Embedded patient chat (tasks.md 14.3) -- `<RequireAuth>`-wrapped like every
// other portal view; the actual streaming logic lives in `ChatWidget` so it
// can be exercised independently of routing in its own test file.
export default function ChatPage() {
  return (
    <RequireAuth>
      <div className="flex flex-1 items-start justify-center px-4 py-16">
        <ChatWidget />
      </div>
    </RequireAuth>
  );
}
