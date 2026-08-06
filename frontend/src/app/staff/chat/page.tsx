"use client";

import { RequireStaffAuth } from "@/lib/auth/require-staff-auth";
import { ChatWidget } from "@/components/chat/chat-widget";

export default function StaffChatPage() {
  return (
    <RequireStaffAuth>
      <div className="flex flex-1 items-start justify-center px-4 py-16">
        <ChatWidget />
      </div>
    </RequireStaffAuth>
  );
}
