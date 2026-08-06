"use client";

import { RequireAuth } from "@/lib/auth/require-auth";
import { ChatWidget } from "@/components/chat/chat-widget";

export default function ChatPage() {
  return (
    <RequireAuth>
      <div className="flex flex-1 items-start justify-center px-4 py-16">
        <ChatWidget />
      </div>
    </RequireAuth>
  );
}
