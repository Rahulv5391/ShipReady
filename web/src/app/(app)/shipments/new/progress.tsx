"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { DOCUMENT_NAMES } from "@/lib/documents";
import { READINESS } from "@/lib/format";
import type { Readiness, RunOut } from "@/lib/types";

export type Uploaded = { id: string; filename: string; fromDrive: boolean };
type Stage = "reading" | "extracting" | "checking" | "drafting" | "review";
type Read = { pages: number; documents: string[] };
type State = {
  stage: Stage;
  read: Record<string, Read>;
  waiting: boolean;
  readiness: Readiness | null;
  failed: string | null;
  unreachable: boolean;
};

const STAGES: { id: Stage; label: string; sub: string }[] = [
  { id: "reading", label: "Reading", sub: "Every page" },
  { id: "extracting", label: "Extracting", sub: "Every field" },
  { id: "checking", label: "Checking", sub: "Against each other" },
  { id: "drafting", label: "Drafting", sub: "Messages" },
  { id: "review", label: "Your review", sub: "You decide" },
];

/** Follows the shipment's run live (GET /runs/{id}/events through the web app's relay). */
function useRunProgress(shipmentId: string): State {
  const [state, setState] = useState<State>({
    stage: "reading",
    read: {},
    waiting: false,
    readiness: null,
    failed: null,
    unreachable: false,
  });
  useEffect(() => {
    let source: EventSource | null = null;
    let stopped = false;
    const update = (change: (current: State) => Partial<State>) =>
      setState((current) => ({ ...current, ...change(current) }));
    const data = (event: Event) => JSON.parse((event as MessageEvent<string>).data) as Record<string, unknown>;

    fetch(`/api/shipments/${shipmentId}/runs`)
      .then((response) => (response.ok ? (response.json() as Promise<RunOut[]>) : Promise.reject()))
      .then((runs) => {
        if (stopped || runs.length === 0) return;
        source = new EventSource(`/api/runs/${runs[0].id}/events`);
        const end = () => source?.close();
        source.addEventListener("stage_started", (event) =>
          update(() => ({ stage: data(event).stage as Stage, waiting: false })),
        );
        source.addEventListener("document_read", (event) => {
          const { file, pages, documents } = data(event) as { file: string; pages: number; documents: string[] };
          update((current) => ({ read: { ...current.read, [file]: { pages, documents } } }));
        });
        source.addEventListener("waiting", () => update(() => ({ waiting: true })));
        source.addEventListener("awaiting_review", (event) => {
          update(() => ({ stage: "review", waiting: false, readiness: data(event).readiness as Readiness }));
          end();
        });
        source.addEventListener("run_failed", (event) => {
          update(() => ({ failed: String(data(event).error ?? "the run stopped") }));
          end();
        });
        source.addEventListener("run_done", end);
      })
      .catch(() => update(() => ({ unreachable: true })));
    return () => {
      stopped = true;
      source?.close();
    };
  }, [shipmentId]);
  return state;
}

function fileDetail(file: Uploaded, read: Read | undefined): string {
  const lower = file.filename.toLowerCase();
  const origin = file.fromDrive ? "Imported from Google Drive" : lower.endsWith(".docx") ? "Converted from Word" : "";
  if (!read) return origin ? `${origin}, being read` : "Being read";
  const unit = lower.endsWith(".xlsx") ? "sheet" : "page";
  const size = `${read.pages} ${unit}${read.pages === 1 ? "" : "s"}`;
  return origin ? `${origin}, ${size}` : size;
}

export function Progress({
  shipmentId,
  reference,
  uploaded,
  duplicates,
  onAddMore,
}: {
  shipmentId: string;
  reference: string;
  uploaded: Uploaded[];
  duplicates: { filename: string; same_as: string }[];
  onAddMore: () => void;
}) {
  const state = useRunProgress(shipmentId);
  const current = STAGES.findIndex((stage) => stage.id === state.stage);
  const readCount = uploaded.filter((file) => state.read[file.filename]).length;
  const verdict = state.readiness ? READINESS[state.readiness] : null;

  return (
    <section aria-label="Upload progress" className="flex flex-col gap-5 card p-6">
      <div role="status" className="flex items-start gap-3">
        <span className="grid size-9 flex-none place-items-center rounded-full bg-ready-soft text-ready">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M5.5 10.3l3 3 6-6.3" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <span className="flex flex-col gap-0.5">
          <span className="font-display text-lg font-semibold">
            {uploaded.length === 0
              ? "Nothing new to upload."
              : state.stage === "review"
                ? "Checked. It's waiting for your review."
                : `Uploaded ${uploaded.length} ${uploaded.length === 1 ? "file" : "files"}. Checking has started.`}
          </span>
          <span className="text-muted">
            You can leave this page; <span className="font-mono text-ink">{reference}</span> shows its progress in Shipments.
          </span>
        </span>
      </div>

      {duplicates.map((duplicate) => (
        <div key={duplicate.filename} role="note" className="flex items-start gap-2.5 rounded-[10px] bg-sunken px-3.5 py-3 text-[13.5px]">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true" className="mt-px flex-none text-muted">
            <rect x="5.5" y="5.5" width="9.5" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M3 12V4a1.5 1.5 0 011.5-1.5H11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <span>
            {duplicate.filename === duplicate.same_as ? (
              <>You added <b>{duplicate.filename}</b> twice, so it was uploaded once.</>
            ) : (
              <><b>{duplicate.filename}</b> is the same file as <b>{duplicate.same_as}</b>, so it was uploaded once.</>
            )}
          </span>
        </div>
      ))}

      {state.failed ? (
        <div role="alert" className="rounded-[10px] bg-fix-soft px-3.5 py-3 text-fix">
          Checking stopped: {state.failed}
        </div>
      ) : state.unreachable ? (
        <div role="alert" className="rounded-[10px] bg-review-soft px-3.5 py-3 text-review">
          Live progress isn&apos;t available right now. The shipment is still being checked; see Shipments.
        </div>
      ) : (
        <ol aria-label="Stages" className="grid grid-cols-[repeat(auto-fit,minmax(110px,1fr))] gap-2">
          {STAGES.map((stage, index) => {
            const done = index < current;
            const now = index === current;
            return (
              <li key={stage.id} aria-current={now ? "step" : undefined} className="flex flex-col gap-1">
                <span className={`h-1.5 rounded-[3px] ${done || now ? "bg-primary" : "bg-track"} ${now && stage.id !== "review" ? "animate-pulse" : ""}`} />
                <span className={`font-semibold ${done || now ? "text-ink" : "text-muted"}`}>{stage.label}</span>
                <span className="text-[13px] text-muted">
                  {stage.id === "reading" && (done || now)
                    ? `${readCount} of ${uploaded.length} files`
                    : now && state.waiting
                      ? "Waiting for the AI service"
                      : stage.id === "review" && verdict
                        ? verdict.label
                        : stage.sub}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      <ul aria-label="Files" className="flex flex-col divide-y divide-line rounded-[10px] border border-line">
        {uploaded.map((file) => {
          const read = state.read[file.filename];
          return (
            <li key={file.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              {read ? (
                <svg width="28" height="28" viewBox="0 0 32 32" fill="none" role="img" aria-label="Read" className="text-ready">
                  <circle cx="16" cy="16" r="13" fill="currentColor" opacity=".14" />
                  <path d="M10.5 16.3l3.6 3.6 7.4-8" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <svg width="28" height="28" viewBox="0 0 32 32" fill="none" role="img" aria-label="Being read" className="animate-spin text-primary">
                  <circle cx="16" cy="16" r="13" stroke="var(--track)" strokeWidth="3" />
                  <path d="M16 3a13 13 0 0113 13" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                </svg>
              )}
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-medium">{file.filename}</span>
                <span className="text-[13px] text-muted">{fileDetail(file, read)}</span>
              </span>
              <span className="flex flex-wrap gap-1.5">
                {read?.documents.map((type, index) => (
                  <span key={`${type}-${index}`} className="chip bg-primary-soft text-primary">
                    {DOCUMENT_NAMES[type] ?? type}
                  </span>
                ))}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap justify-end gap-2.5">
        <button
          type="button"
          onClick={onAddMore}
          className="btn btn-md btn-secondary"
        >
          Add more files
        </button>
        <Link href={`/shipments/${shipmentId}`} className="btn btn-md btn-primary">
          Open the report
        </Link>
      </div>
    </section>
  );
}
