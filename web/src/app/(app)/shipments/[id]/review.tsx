"use client";

import { useState, useTransition } from "react";

import { messageText } from "@/lib/review";
import type { MessageOut } from "@/lib/types";

import { checkAgain, decide, updateMessage, type Outcome } from "./actions";

const BUTTON = "rounded-[10px] px-3.5 py-2 text-[13.5px] font-semibold disabled:opacity-50";
const PRIMARY = `${BUTTON} bg-primary text-primary-ink hover:opacity-90`;
const SECONDARY = `${BUTTON} border border-line-strong bg-surface hover:bg-sunken`;

function useAction() {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const run = (action: () => Promise<Outcome>, done?: () => void) =>
    start(async () => {
      const outcome = await action();
      if ("error" in outcome) setError(outcome.error);
      else {
        setError(null);
        done?.();
      }
    });
  return { pending, error, run };
}

export type ReviewState = "review" | "running" | "closed";

/** The decision buttons of a shipment's report, with a panel to confirm the one chosen. */
export function ReviewActions({
  shipmentId,
  state,
  blockers,
}: {
  shipmentId: string;
  state: ReviewState;
  blockers: number;
}) {
  const [open, setOpen] = useState<"ready" | "needs_fix" | null>(null);
  const [reason, setReason] = useState("");
  const { pending, error, run } = useAction();
  const reasonNeeded = open === "ready" && blockers > 0;

  if (state === "running") {
    return <p className="rounded-[10px] bg-primary-soft px-3.5 py-2 text-[13.5px] font-semibold text-primary">Being checked</p>;
  }
  if (state === "closed") {
    return (
      <div className="flex flex-col items-end gap-1.5">
        <button type="button" className={SECONDARY} disabled={pending} onClick={() => run(() => checkAgain(shipmentId))}>
          {pending ? "Starting" : "Check again"}
        </button>
        {error && <p role="alert" className="text-[13px] text-fix">{error}</p>}
      </div>
    );
  }
  return (
    <div className="relative flex w-full flex-col gap-2 sm:w-auto sm:items-end">
      <div className="flex flex-wrap gap-2 sm:justify-end">
        <button type="button" className={SECONDARY} aria-expanded={open === "needs_fix"} onClick={() => setOpen(open === "needs_fix" ? null : "needs_fix")}>
          Send back to fix
        </button>
        <button type="button" className={PRIMARY} aria-expanded={open === "ready"} onClick={() => setOpen(open === "ready" ? null : "ready")}>
          Mark ready
        </button>
      </div>
      {open && (
        <form
          className="flex w-full flex-col gap-2.5 rounded-[14px] border border-line bg-surface p-4 shadow-[var(--nav-shadow)] sm:absolute sm:right-0 sm:top-full sm:z-10 sm:mt-2 sm:w-[440px]"
          onSubmit={(event) => {
            event.preventDefault();
            run(() => decide(shipmentId, open, reason), () => setOpen(null));
          }}
        >
          <p className="text-[14px]">
            {open === "needs_fix"
              ? "The shipment goes back for corrected documents. Uploading them starts a new check."
              : blockers > 0
                ? `${blockers} blocker ${blockers === 1 ? "check fails" : "checks fail"}. Marking it ready means you've confirmed it can be filed anyway.`
                : "The shipment is marked ready to file."}
          </p>
          <label htmlFor="reason" className="text-[13px] font-semibold">
            {reasonNeeded ? "Why it can be filed" : "Note (optional)"}
          </label>
          <textarea
            id="reason"
            rows={3}
            required={reasonNeeded}
            maxLength={2000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-[14px]"
          />
          {error && <p role="alert" className="text-[13px] text-fix">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" className={SECONDARY} onClick={() => setOpen(null)}>
              Cancel
            </button>
            <button type="submit" className={PRIMARY} disabled={pending || (reasonNeeded && !reason.trim())}>
              {pending ? "Saving" : open === "ready" ? "Mark ready" : "Send back to fix"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** A drafted message: edit it, approve or discard it, and copy it into an email. ShipReady
 * never sends it. */
export function MessageCard({ shipmentId, message, to }: { shipmentId: string; message: MessageOut; to: string }) {
  const [subject, setSubject] = useState(message.subject);
  const [body, setBody] = useState(message.body);
  const [discarding, setDiscarding] = useState(false);
  const [copied, setCopied] = useState(false);
  const { pending, error, run } = useAction();
  const draft = message.status === "draft";
  const changed = subject !== message.subject || body !== message.body;
  const edits = changed ? { subject, body } : {};

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(messageText(subject, body));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex flex-col gap-2.5">
      <label htmlFor={`subject-${message.id}`} className="text-[12.5px] font-semibold text-muted">Subject</label>
      <input
        id={`subject-${message.id}`}
        value={subject}
        readOnly={!draft}
        onChange={(event) => setSubject(event.target.value)}
        className="rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-[14px] read-only:border-line read-only:bg-sunken"
      />
      <label htmlFor={`body-${message.id}`} className="text-[12.5px] font-semibold text-muted">Message to {to}</label>
      <textarea
        id={`body-${message.id}`}
        rows={10}
        value={body}
        readOnly={!draft}
        onChange={(event) => setBody(event.target.value)}
        className="rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-[14px] leading-relaxed read-only:border-line read-only:bg-sunken"
      />
      {error && <p role="alert" className="text-[13px] text-fix">{error}</p>}
      {discarding ? (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="mr-auto text-[13.5px]">Discard this draft? It can&rsquo;t be brought back.</span>
          <button type="button" className={SECONDARY} onClick={() => setDiscarding(false)}>Keep it</button>
          <button
            type="button"
            className={`${BUTTON} bg-fix text-surface hover:opacity-90`}
            disabled={pending}
            onClick={() => run(() => updateMessage(shipmentId, message.id, { decision: "discard" }), () => setDiscarding(false))}
          >
            Discard
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap justify-end gap-2">
          {draft && (
            <button type="button" className={`${BUTTON} mr-auto text-fix hover:bg-fix-soft`} onClick={() => setDiscarding(true)}>
              Discard
            </button>
          )}
          {message.status !== "discarded" && (
            <button type="button" className={SECONDARY} onClick={copy} aria-live="polite">
              {copied ? "Copied" : "Copy text"}
            </button>
          )}
          {draft && changed && (
            <button type="button" className={SECONDARY} disabled={pending} onClick={() => run(() => updateMessage(shipmentId, message.id, edits))}>
              Save
            </button>
          )}
          {draft && (
            <button
              type="button"
              className={PRIMARY}
              disabled={pending}
              onClick={() => run(() => updateMessage(shipmentId, message.id, { ...edits, decision: "approve" }))}
            >
              {pending ? "Saving" : changed ? "Save and approve" : "Approve"}
            </button>
          )}
        </div>
      )}
      {draft && (
        <p className="text-[12.5px] text-muted">ShipReady never sends messages for you. Approving records your decision; copy the text into your email.</p>
      )}
    </div>
  );
}
