import { Avatar } from "@/components/avatar";
import { RECIPIENTS } from "@/lib/report";
import type { MessageOut } from "@/lib/types";

import { MessageCard } from "./review";

const STATUS_TONES: Record<MessageOut["status"], string> = {
  draft: "bg-review-soft text-review",
  approved: "bg-ready-soft text-ready",
  discarded: "bg-sunken text-muted",
};

/** The drafted messages, one line each; opening a line shows the message to read, edit and decide. */
export function MessageList({ shipmentId, messages }: { shipmentId: string; messages: MessageOut[] }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {messages.map((message) => {
        const to = RECIPIENTS[message.recipient] ?? message.recipient;
        return (
          <li key={message.id}>
            <details className="group">
              <summary className="disclosure -mx-2 flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-sunken">
                <Avatar name={to} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold">{to}</span>
                  <span className="truncate text-[13px] text-muted group-open:whitespace-normal" title={message.subject}>{message.subject}</span>
                </span>
                <span className={`chip capitalize ${STATUS_TONES[message.status]}`}>{message.status}</span>
              </summary>
              <div className="pt-3">
                <MessageCard key={`${message.id}-${message.status}`} shipmentId={shipmentId} message={message} to={to} />
              </div>
            </details>
          </li>
        );
      })}
    </ul>
  );
}
