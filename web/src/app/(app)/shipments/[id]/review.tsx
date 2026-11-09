"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { ACCEPT, MAX_FILE_BYTES, accepted } from "@/lib/documents";
import { STAGES } from "@/lib/format";
import { messageText, reviewError } from "@/lib/review";
import type { MessageOut } from "@/lib/types";

import { checkAgain, decide, removeDocument, updateMessage, type Outcome } from "./actions";

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
  activeRun,
}: {
  shipmentId: string;
  state: ReviewState;
  blockers: number;
  activeRun: { id: string; after: number } | null;
}) {
  const [open, setOpen] = useState<"ready" | "needs_fix" | null>(null);
  const [reason, setReason] = useState("");
  const { pending, error, run } = useAction();
  const reasonNeeded = open === "ready" && blockers > 0;

  if (state === "running") return activeRun ? <RunWatcher runId={activeRun.id} after={activeRun.after} /> : null;
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

/** Follows a running check live and shows its stage; when it waits for review or stops, the
 * report is read again. Only events after the ones the page was drawn with count, as a run
 * reopened by a correction already holds its earlier "awaiting review". */
function RunWatcher({ runId, after }: { runId: string; after: number }) {
  const router = useRouter();
  const [label, setLabel] = useState("Starting");
  useEffect(() => {
    const source = new EventSource(`/api/runs/${runId}/events?after=${after}`);
    const data = (event: Event) => JSON.parse((event as MessageEvent<string>).data) as Record<string, unknown>;
    source.addEventListener("stage_started", (event) => {
      const stage = data(event).stage as keyof typeof STAGES;
      setLabel(STAGES[stage] ?? "Checking");
    });
    source.addEventListener("document_read", (event) => setLabel(`Read ${String(data(event).file)}`));
    source.addEventListener("waiting", () => setLabel("Waiting for the AI service"));
    const finished = () => {
      source.close();
      router.refresh();
    };
    for (const name of ["awaiting_review", "run_failed", "run_done"]) source.addEventListener(name, finished);
    return () => source.close();
  }, [runId, after, router]);
  return (
    <p role="status" className="flex items-center gap-2 rounded-[10px] bg-primary-soft px-3.5 py-2 text-[13.5px] font-semibold text-primary">
      <span className="size-2 animate-pulse rounded-full bg-primary" aria-hidden="true" />
      Being checked: {label}
    </p>
  );
}

/** Replace a file with a corrected one, or take it out; either checks the shipment again. */
export function DocumentActions({
  shipmentId,
  documentId,
  filename,
  removable,
  disabled,
}: {
  shipmentId: string;
  documentId: string;
  filename: string;
  removable: boolean;
  disabled: boolean;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [removing, setRemoving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const { pending, error, run } = useAction();

  const replace = async (file: File) => {
    if (!accepted(file.name)) {
      setNotice(`${file.name} isn't a file ShipReady reads. Use PDF, Word, Excel or an image.`);
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setNotice(`${file.name} is larger than 25 MB.`);
      return;
    }
    setUploading(true);
    setNotice(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`/api/documents/${documentId}:replace`, { method: "POST", body: form });
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown; duplicates?: { same_as: string }[] };
      if (!response.ok) setNotice(reviewError(response.status, typeof body.detail === "string" ? body.detail : ""));
      else if (body.duplicates?.length) setNotice(`That's the same file as ${body.duplicates[0].same_as}. Nothing changed.`);
      else router.refresh();
    } catch {
      setNotice("ShipReady's server didn't answer. Try again.");
    } finally {
      setUploading(false);
    }
  };

  const message = notice ?? error;
  return (
    <div className="flex flex-none flex-col items-end gap-1">
      {removing ? (
        <span className="flex items-center gap-2 text-[12.5px]">
          Remove it?
          <button type="button" className="font-semibold text-muted hover:underline" onClick={() => setRemoving(false)}>
            Keep
          </button>
          <button
            type="button"
            className="font-semibold text-fix hover:underline disabled:opacity-50"
            disabled={pending}
            onClick={() => run(() => removeDocument(shipmentId, documentId), () => setRemoving(false))}
          >
            Remove
          </button>
        </span>
      ) : (
        <span className="flex gap-3 text-[12.5px] font-semibold">
          <button
            type="button"
            className="text-primary hover:underline disabled:opacity-50"
            disabled={disabled || uploading}
            onClick={() => input.current?.click()}
          >
            {uploading ? "Uploading" : "Replace"}
          </button>
          {removable && (
            <button
              type="button"
              className="text-muted hover:text-fix hover:underline disabled:opacity-50"
              disabled={disabled}
              onClick={() => setRemoving(true)}
            >
              Remove
            </button>
          )}
        </span>
      )}
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        hidden
        aria-label={`Corrected file for ${filename}`}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void replace(file);
        }}
      />
      {message && (
        <p role="alert" className="max-w-[240px] text-right text-[12.5px] text-fix">
          {message}
        </p>
      )}
    </div>
  );
}
