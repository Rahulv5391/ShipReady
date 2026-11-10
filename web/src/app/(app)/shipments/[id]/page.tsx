import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Fragment, Suspense } from "react";

import { TONES, ToneIcon } from "@/components/tone";
import { ApiError, api } from "@/lib/api";
import { DOCUMENT_NAMES, kindOf } from "@/lib/documents";
import { compareEvidence } from "@/lib/evidence";
import { ruleHref } from "@/lib/rules";
import { MODES, READINESS, timeAgo } from "@/lib/format";
import {
  RECIPIENTS,
  SEVERITY_LABELS,
  TABS,
  approvalLine,
  checksFor,
  collapseRepeats,
  fieldLabel,
  eventLine,
  initials,
  parseTab,
  readableMessage,
  verdictSentence,
  type ActivityLine,
  type Tab,
} from "@/lib/report";
import type {
  ApprovalOut,
  CheckOut,
  EventOut,
  MessageOut,
  RunOut,
  ShipmentDetail,
} from "@/lib/types";

import { DocumentActions, MessageCard, ReviewActions, type ReviewState } from "./review";

export const metadata: Metadata = { title: "Readiness report" };

const CIRCLE = 2 * Math.PI * 48; // the score ring's circumference

type Data = {
  shipment: ShipmentDetail;
  checks: CheckOut[];
  messages: MessageOut[];
  approvals: ApprovalOut[];
  events: EventOut[];
  runId: string | null;
};

async function load(id: string): Promise<Data> {
  try {
    const [shipment, checks, messages, approvals, runs] = await Promise.all([
      api<ShipmentDetail>(`/shipments/${id}`),
      api<CheckOut[]>(`/shipments/${id}/checks`),
      api<MessageOut[]>(`/shipments/${id}/messages`),
      api<ApprovalOut[]>(`/shipments/${id}/approvals`),
      api<RunOut[]>(`/shipments/${id}/runs`),
    ]);
    const events = runs.length > 0 ? await api<EventOut[]>(`/runs/${runs[0].id}/log`) : [];
    // Messages of earlier runs were decided then; their decisions stay in the activity.
    const current = messages.filter((m) => m.run_id === runs[0]?.id);
    return { shipment, checks, messages: current, approvals, events, runId: runs[0]?.id ?? null };
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) notFound();
    throw error;
  }
}

function SeverityIcon({ severity }: { severity: CheckOut["severity"] }) {
  if (severity === "blocker") {
    return (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
        <path d="M6.2 2h5.6L16 6.2v5.6L11.8 16H6.2L2 11.8V6.2z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M9 5.5v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="9" cy="12.3" r="1" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M9 2.5l7 12.5H2z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M9 7v3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="9" cy="12.8" r="1" fill="currentColor" />
    </svg>
  );
}

function Values({ check, indices }: { check: CheckOut; indices: number[] }) {
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1 text-[13px]">
      {indices.map((index) => {
        const field = check.evidence[index];
        return (
          <Fragment key={`${field.document_id}-${field.path}`}>
            <dt className="text-muted">{fieldLabel(field.path)}</dt>
            <dd className="break-words font-mono">{field.value}</dd>
          </Fragment>
        );
      })}
    </dl>
  );
}

const SEVERITY_TONES: Record<CheckOut["severity"], string> = {
  blocker: "bg-fix-soft text-fix",
  major: "bg-review-soft text-review",
  minor: "bg-sunken text-muted",
  info: "bg-sunken text-muted",
};

function Finding({ check, shipmentId }: { check: CheckOut; shipmentId: string }) {
  const serious = check.severity === "blocker" ? "text-fix" : check.severity === "major" ? "text-review" : "text-muted";
  const { differs, agrees } = compareEvidence(check.evidence);
  const citation = check.citations[0];
  return (
    <article className="flex gap-3.5 border-t border-line px-5 py-5 first:border-t-0">
      <span className={`mt-0.5 flex-none ${check.outcome === "fail" ? serious : "text-review"}`}>
        <SeverityIcon severity={check.severity} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-semibold leading-snug">{check.title}</h3>
            <span className={`flex-none rounded-md px-2 py-0.5 text-[12px] font-semibold ${SEVERITY_TONES[check.severity]}`}>
              {SEVERITY_LABELS[check.severity]}
            </span>
          </div>
          {check.message && <p className="text-[14px] text-muted">{readableMessage(check.message)}</p>}
        </div>
        {differs.length > 0 && (
          <div className="flex flex-col gap-2 rounded-lg bg-sunken px-3.5 py-3">
            <Values check={check} indices={differs} />
            {agrees.length > 0 && (
              <details className="group">
                <summary className="cursor-pointer list-none text-[12.5px] font-medium text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
                  <span className="group-open:hidden">Show {agrees.length} matching {agrees.length === 1 ? "value" : "values"}</span>
                  <span className="hidden group-open:inline">Hide matching values</span>
                </summary>
                <div className="mt-2 border-t border-line pt-2 opacity-80">
                  <Values check={check} indices={agrees} />
                </div>
              </details>
            )}
          </div>
        )}
        {check.critic_reason && (
          <p className="text-[13px] text-muted">
            <b className="font-semibold text-ink">
              {check.verification === "misread" ? "Looks like a misreading." : "Re-read on the page image."}
            </b>{" "}
            {check.critic_reason}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
          {check.evidence.length > 0 && (
            <Link
              href={`/shipments/${shipmentId}/checks/${encodeURIComponent(check.rule_id)}`}
              className="font-semibold text-primary hover:underline"
            >
              Show on the page
            </Link>
          )}
          {citation && (
            <a href={citation.url} target="_blank" rel="noreferrer" className="min-w-0 truncate text-muted hover:text-ink hover:underline" title={citation.text}>
              {citation.title}
              {citation.page ? `, page ${citation.page}` : ""}
            </a>
          )}
          <Link href={ruleHref(check.rule_id)} className="ml-auto font-mono text-[11.5px] text-muted hover:text-primary hover:underline" title="What this check means">
            {check.rule_id}
          </Link>
        </div>
      </div>
    </article>
  );
}

const ACTIVITY_SHOWN = 5;

function ActivityList({ lines }: { lines: ActivityLine[] }) {
  return (
    <ol className="flex flex-col gap-3">
      {lines.map((line) => (
        <li key={line.key} className="flex gap-2.5">
          <span className="mt-[7px] size-2 flex-none rounded-full bg-line-strong" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="font-medium">{line.what}</span>
            {line.detail && <span className="truncate text-[13px] text-muted" title={line.detail}>{line.detail}</span>}
          </span>
          <span className="flex-none text-[12.5px] text-muted">{timeAgo(line.at)}</span>
        </li>
      ))}
    </ol>
  );
}

async function Report({ ids, tab }: { ids: Promise<{ id: string }>; tab: Promise<string | undefined> }) {
  const { id } = await ids;
  const [{ shipment, checks, messages, approvals, events, runId }, show] = await Promise.all([load(id), tab]);
  const current: Tab = parseTab(show);
  const verdict = shipment.readiness ? READINESS[shipment.readiness] : null;
  const score = shipment.readiness_score === null ? null : Number(shipment.readiness_score);
  const counts = Object.fromEntries(TABS.map((t) => [t.id, checks.filter((c) => c.outcome === t.outcome).length])) as Record<Tab, number>;
  const shown = checksFor(checks, TABS.find((t) => t.id === current)!.outcome);
  const checkedAt = [...events].reverse().find((e) => e.type === "checks_done")?.at;
  const title =
    shipment.exporter && shipment.consignee ? `${shipment.exporter} to ${shipment.consignee}` : shipment.reference;
  const route = [
    shipment.mode ? `${MODES[shipment.mode].toLowerCase()} freight` : null,
    shipment.port_of_loading && shipment.port_of_discharge ? `from ${shipment.port_of_loading} to ${shipment.port_of_discharge}` : null,
  ].filter(Boolean).join(" ");
  const drafts = messages.filter((m) => m.status === "draft");
  const activity = collapseRepeats([
    ...events.flatMap((e) => {
      const line = eventLine(e);
      return line ? [{ key: `e${e.id}`, at: e.at, order: e.id, ...line }] : [];
    }),
    ...approvals.map((a) => ({ key: a.id, at: a.decided_at, order: 0, ...approvalLine(a) })),
  ]
    // Newest first. Events of one transaction share a time, so their recorded order decides.
    .sort((a, b) => b.at.localeCompare(a.at) || b.order - a.order));
  const files = shipment.documents.length;
  const found = shipment.documents.reduce((sum, d) => sum + d.parts.length, 0);
  const state: ReviewState =
    shipment.run?.status === "awaiting_review" ? "review" : shipment.run?.status === "running" ? "running" : "closed";
  const blockers = checks.filter((c) => c.outcome === "fail" && c.severity === "blocker").length;
  const decision =
    state === "closed"
      ? approvals
          .filter((a) => a.action === "mark_ready" || a.action === "mark_needs_fix")
          .sort((a, b) => b.decided_at.localeCompare(a.decided_at))[0]
      : undefined;

  return (
    <>
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[13px] text-muted">
        <Link href="/shipments" className="hover:text-ink">Shipments</Link>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M5.5 3.5L9 7l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="font-mono text-ink">{shipment.reference}</span>
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="text-balance font-display text-[30px] font-bold leading-[1.15] tracking-[-0.025em]">{title}</h1>
          <p className="text-base text-muted">
            Shipment <span className="font-mono text-ink">{shipment.reference}</span>
            {route ? `, ${route}` : ""}
          </p>
          {decision && (
            <p className="text-[14px]">
              <b>{approvalLine(decision).what}</b> {approvalLine(decision).detail}, {timeAgo(decision.decided_at)}
            </p>
          )}
        </div>
        <ReviewActions
          shipmentId={id}
          state={state}
          blockers={blockers}
          activeRun={runId ? { id: runId, after: Math.max(0, ...events.map((e) => e.id)) } : null}
        />
      </div>

      <section aria-label="Verdict" className="flex flex-wrap items-center gap-x-8 gap-y-5 rounded-[14px] border border-line bg-surface p-6">
        {verdict ? (
          <div
            role="img"
            aria-label={`Suggested verdict: ${verdict.label}`}
            className={`-rotate-3 rounded-[10px] border-[3px] p-1 ${TONES[verdict.tone].fg} ${verdict.tone === "fix" ? "border-fix" : verdict.tone === "review" ? "border-review" : "border-ready"}`}
          >
            <div className="flex flex-col items-center rounded-[7px] border-[1.5px] border-current px-4 pb-1.5 pt-2">
              <span className="font-display text-[26px] font-extrabold uppercase leading-none tracking-[0.05em]">{verdict.label}</span>
              {checkedAt && (
                <span className="font-mono text-[10px] tracking-[0.08em]">
                  CHECKED {new Date(checkedAt).toLocaleDateString("en-GB").replaceAll("/", ".")}
                </span>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-[10px] border-2 border-dashed border-line-strong px-5 py-4 font-semibold text-muted">Not checked yet</div>
        )}
        {score !== null && (
          <div className="flex items-center gap-4">
            <svg width="112" height="112" viewBox="0 0 112 112" role="img" aria-label={`Score ${score.toFixed(1)} out of 100`}>
              <circle cx="56" cy="56" r="48" fill="none" stroke="var(--track)" strokeWidth="10" />
              <circle
                cx="56"
                cy="56"
                r="48"
                fill="none"
                stroke="var(--ink)"
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={`${(CIRCLE * score) / 100} ${CIRCLE}`}
                transform="rotate(-90 56 56)"
              />
              <text x="56" y="63" textAnchor="middle" fontSize="26" fontWeight="700" fill="var(--ink)" className="font-display">
                {score.toFixed(1)}
              </text>
            </svg>
            <span className="flex flex-col">
              <span className="font-semibold">Readiness score</span>
              <span className="max-w-[24ch] text-[13px] text-muted">Share of the rulebook passed, blockers counting most</span>
            </span>
          </div>
        )}
        <div className="flex min-w-[260px] flex-1 flex-col gap-3">
          <p className="text-[15px]">{verdictSentence(shipment.readiness, checks)}</p>
          <div className="flex flex-wrap gap-5">
            {TABS.map((t) => (
              <span key={t.id} className="flex items-baseline gap-1.5">
                <span className="font-display text-2xl font-bold tabular-nums">{counts[t.id]}</span>
                <span className="text-muted">{t.label.toLowerCase()}</span>
              </span>
            ))}
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-start gap-6">
        <section aria-label="Findings" className="min-w-0 flex-[1_1_540px] overflow-hidden rounded-[14px] border border-line bg-surface">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
            <h2 className="font-display text-lg font-semibold">Findings</h2>
            <div role="tablist" aria-label="Findings by outcome" className="ml-auto flex rounded-[10px] bg-sunken p-[3px]">
              {TABS.map((t) => (
                <Link
                  key={t.id}
                  href={t.id === "failed" ? `/shipments/${id}` : `/shipments/${id}?show=${t.id}`}
                  role="tab"
                  aria-selected={current === t.id}
                  scroll={false}
                  className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold ${current === t.id ? "bg-surface text-ink shadow-[0_1px_2px_rgba(26,31,43,.08)]" : "text-muted"}`}
                >
                  {t.label} {counts[t.id]}
                </Link>
              ))}
            </div>
          </div>
          {shown.length === 0 ? (
            <p className="px-5 py-10 text-center text-muted">
              {checks.length === 0 ? "The checks haven't run yet." : current === "failed" ? "No check failed." : current === "confirm" ? "Nothing to confirm." : "No check passed yet."}
            </p>
          ) : current === "passed" ? (
            // Code first in a column of its own, so codes line up and a long title wraps beside it.
            <ul className="grid gap-x-8 px-5 py-2 xl:grid-cols-2">
              {shown.map((check) => (
                <li key={check.rule_id} className="grid grid-cols-[18px_64px_minmax(0,1fr)] items-start gap-x-2.5 border-b border-line py-2.5 last:border-b-0 xl:[&:nth-last-child(2):nth-child(odd)]:border-b-0">
                  <span className="mt-px text-ready"><ToneIcon tone="ready" /></span>
                  <Link href={ruleHref(check.rule_id)} className="pt-px font-mono text-[12px] text-muted hover:text-primary hover:underline" title="What this check means">
                    {check.rule_id}
                  </Link>
                  <span className="text-[14px] leading-snug">{check.title}</span>
                </li>
              ))}
            </ul>
          ) : (
            shown.map((check) => <Finding key={check.rule_id} check={check} shipmentId={id} />)
          )}
        </section>

        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
          <section aria-label="Messages to send" className="flex flex-col gap-3 rounded-[14px] border border-line bg-surface p-5">
            <div className="flex flex-col gap-1">
              <h2 className="font-display text-base font-semibold">Messages to send</h2>
              <p className="text-[13px] text-muted">
                {drafts.length > 0
                  ? `${drafts.length} ${drafts.length === 1 ? "draft waits" : "drafts wait"} for your approval. Open one to read, edit and approve it.`
                  : "Drafted for the party who issued each document. You approve and send them."}
              </p>
            </div>
            {messages.length === 0 ? (
              <p className="text-[13px] text-muted">No messages drafted.</p>
            ) : (
              <ul className="flex flex-col gap-2.5">
                {messages.map((message) => {
                  const to = RECIPIENTS[message.recipient] ?? message.recipient;
                  return (
                    <li key={message.id}>
                      <details className="group">
                        <summary className="flex cursor-pointer list-none items-center gap-2.5 rounded-lg py-1 [&::-webkit-details-marker]:hidden">
                          <span className="grid size-8 flex-none place-items-center rounded-full bg-primary-soft text-[12px] font-bold text-primary">{initials(to)}</span>
                          <span className="flex min-w-0 flex-1 flex-col">
                            <span className="font-semibold">{to}</span>
                            <span className="truncate text-[13px] text-muted group-open:whitespace-normal" title={message.subject}>{message.subject}</span>
                          </span>
                          <span className={`rounded-md px-2 py-0.5 text-[12px] font-semibold capitalize ${message.status === "approved" ? "bg-ready-soft text-ready" : message.status === "discarded" ? "bg-sunken text-muted" : "bg-review-soft text-review"}`}>
                            {message.status}
                          </span>
                        </summary>
                        <div className="pt-3">
                          <MessageCard key={`${message.id}-${message.status}`} shipmentId={id} message={message} to={to} />
                        </div>
                      </details>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section aria-label="Documents in this shipment" className="flex flex-col gap-3 rounded-[14px] border border-line bg-surface p-5">
            <div className="flex flex-col gap-1">
              <h2 className="font-display text-base font-semibold">Documents</h2>
              <p className="text-[13px] text-muted">
                {found} {found === 1 ? "document" : "documents"} found in {files} {files === 1 ? "file" : "files"}
              </p>
            </div>
            <ul className="flex flex-col gap-2.5">
              {shipment.documents.map((document) => (
                <li key={document.id} className="flex items-start gap-2.5">
                  <span className="mt-0.5 w-12 flex-none rounded-md bg-sunken py-0.5 text-center text-[11.5px] font-semibold text-muted">{kindOf(document.filename)}</span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="font-semibold">
                      {document.parts.length > 0
                        ? document.parts.map((p) => DOCUMENT_NAMES[p.doc_type] ?? p.doc_type).join(", ")
                        : document.status === "failed" ? "Could not be read" : "Being read"}
                    </span>
                    <span className="truncate text-[13px] text-muted" title={document.filename}>{document.filename}</span>
                  </span>
                  <DocumentActions
                    shipmentId={id}
                    documentId={document.id}
                    filename={document.filename}
                    removable={files > 1}
                    disabled={state === "running"}
                  />
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Activity" className="flex flex-col gap-3 rounded-[14px] border border-line bg-surface p-5">
            <h2 className="font-display text-base font-semibold">Activity</h2>
            <ActivityList lines={activity.slice(0, ACTIVITY_SHOWN)} />
            {activity.length > ACTIVITY_SHOWN && (
              <details className="group">
                <summary className="cursor-pointer list-none text-[13px] font-medium text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
                  <span className="group-open:hidden">Show {activity.length - ACTIVITY_SHOWN} earlier</span>
                  <span className="hidden group-open:inline">Hide earlier</span>
                </summary>
                <div className="pt-3">
                  <ActivityList lines={activity.slice(ACTIVITY_SHOWN)} />
                </div>
              </details>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

function ReportSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the report" className="flex flex-col gap-6">
      <div className="h-[72px] w-2/3 animate-pulse rounded-[14px] bg-surface" />
      <div className="h-[160px] animate-pulse rounded-[14px] bg-surface" />
      <div className="h-[420px] animate-pulse rounded-[14px] bg-surface" />
    </div>
  );
}

export default function ReportPage({ params, searchParams }: PageProps<"/shipments/[id]">) {
  // Read inside the boundary: the address is request data, so the frame prerenders without it.
  const tab = searchParams.then((s) => (typeof s.show === "string" ? s.show : undefined));
  return (
    <Suspense fallback={<ReportSkeleton />}>
      <Report ids={params} tab={tab} />
    </Suspense>
  );
}
