import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { TONES, ToneIcon } from "@/components/tone";
import { ApiError, api } from "@/lib/api";
import { DOCUMENT_NAMES, kindOf } from "@/lib/documents";
import { MODES, READINESS, timeAgo } from "@/lib/format";
import {
  RECIPIENTS,
  SEVERITY_LABELS,
  TABS,
  approvalLine,
  checksFor,
  fieldLabel,
  eventLine,
  initials,
  parseTab,
  verdictSentence,
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

export const metadata: Metadata = { title: "Readiness report" };

const CIRCLE = 2 * Math.PI * 48; // the score ring's circumference

type Data = {
  shipment: ShipmentDetail;
  checks: CheckOut[];
  messages: MessageOut[];
  approvals: ApprovalOut[];
  events: EventOut[];
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
    return { shipment, checks, messages, approvals, events };
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

function Finding({ check, shipmentId }: { check: CheckOut; shipmentId: string }) {
  const serious = check.severity === "blocker" ? "text-fix" : check.severity === "major" ? "text-review" : "text-muted";
  return (
    <article className="flex gap-3.5 border-t border-line px-5 py-4 first:border-t-0">
      <span className={`mt-0.5 flex-none ${check.outcome === "fail" ? serious : "text-review"}`}>
        <SeverityIcon severity={check.severity} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <h3 className="font-semibold">{check.title}</h3>
          <span className={`text-[12.5px] font-semibold ${serious}`}>{SEVERITY_LABELS[check.severity]}</span>
          <span className="font-mono text-[12px] text-muted">{check.rule_id}</span>
        </div>
        <p className="text-[14px]">{check.message}</p>
        {check.citations.map((citation) => (
          <figure key={citation.source_id} className="rounded-lg border-l-[3px] border-line-strong bg-sunken px-3.5 py-2.5">
            <blockquote className="line-clamp-4 text-[13px] text-muted">{citation.text}</blockquote>
            <figcaption className="mt-1 text-[12.5px] font-semibold">
              <a href={citation.url} target="_blank" rel="noreferrer" className="hover:underline">
                {citation.title}
                {citation.page ? `, page ${citation.page}` : ""}
              </a>
            </figcaption>
          </figure>
        ))}
        {check.evidence.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {check.evidence.map((field) => (
              <span key={`${field.document_id}-${field.path}`} className="inline-flex items-center gap-1.5 rounded-md bg-sunken px-2 py-1 text-[12.5px]">
                <span className="font-semibold">{fieldLabel(field.path)}</span>
                <span className="font-mono text-muted">{field.value}</span>
              </span>
            ))}
            <Link
              href={`/shipments/${shipmentId}/checks/${encodeURIComponent(check.rule_id)}`}
              className="px-1 py-1 text-[12.5px] font-semibold text-primary hover:underline"
            >
              Show on the page
            </Link>
          </div>
        )}
        {check.critic_reason && (
          <p className="flex gap-2 text-[13px] text-muted">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="mt-0.5 flex-none">
              <path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8 12.1 12.5 8 12.5 1.5 8 1.5 8z" stroke="currentColor" strokeWidth="1.3" />
              <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.3" />
            </svg>
            <span>
              <b className="text-ink">
                {check.verification === "misread" ? "Looks like a misreading:" : "Checked on the page image:"}
              </b>{" "}
              {check.critic_reason}
            </span>
          </p>
        )}
      </div>
    </article>
  );
}

async function Report({ ids, tab }: { ids: Promise<{ id: string }>; tab: Promise<string | undefined> }) {
  const { id } = await ids;
  const [{ shipment, checks, messages, approvals, events }, show] = await Promise.all([load(id), tab]);
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
  const activity = [
    ...events.flatMap((e) => {
      const line = eventLine(e);
      return line ? [{ key: `e${e.id}`, at: e.at, order: e.id, ...line }] : [];
    }),
    ...approvals.map((a) => ({ key: a.id, at: a.decided_at, order: 0, ...approvalLine(a) })),
  ]
    // Newest first. Events of one transaction share a time, so their recorded order decides.
    .sort((a, b) => b.at.localeCompare(a.at) || b.order - a.order);
  const files = shipment.documents.length;
  const found = shipment.documents.reduce((sum, d) => sum + d.parts.length, 0);

  return (
    <>
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[13px] text-muted">
        <Link href="/shipments" className="hover:text-ink">Shipments</Link>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M5.5 3.5L9 7l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="font-mono text-ink">{shipment.reference}</span>
      </nav>
      <div className="flex flex-col gap-1.5">
        <h1 className="text-balance font-display text-[30px] font-bold leading-[1.15] tracking-[-0.025em]">{title}</h1>
        <p className="text-base text-muted">
          Shipment <span className="font-mono text-ink">{shipment.reference}</span>
          {route ? `, ${route}` : ""}
        </p>
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
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-x-4 px-5 py-3">
              {shown.map((check) => (
                <li key={check.rule_id} className="flex items-center gap-2 py-1.5">
                  <span className="text-ready"><ToneIcon tone="ready" /></span>
                  <span className="truncate" title={check.title}>{check.title}</span>
                  <span className="ml-auto font-mono text-[11.5px] text-muted">{check.rule_id}</span>
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
              <p className="text-[13px] text-muted">Drafted for the party who issued each document. You approve and send them.</p>
            </div>
            {messages.length === 0 ? (
              <p className="text-[13px] text-muted">No messages drafted.</p>
            ) : (
              <ul className="flex flex-col gap-2.5">
                {messages.map((message) => {
                  const to = RECIPIENTS[message.recipient] ?? message.recipient;
                  return (
                    <li key={message.id} className="flex items-center gap-2.5">
                      <span className="grid size-8 flex-none place-items-center rounded-full bg-primary-soft text-[12px] font-bold text-primary">{initials(to)}</span>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="font-semibold">{to}</span>
                        <span className="truncate text-[13px] text-muted" title={message.subject}>{message.subject}</span>
                      </span>
                      <span className={`rounded-md px-2 py-0.5 text-[12px] font-semibold capitalize ${message.status === "approved" ? "bg-ready-soft text-ready" : message.status === "discarded" ? "bg-sunken text-muted" : "bg-review-soft text-review"}`}>
                        {message.status}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            {drafts.length > 0 && (
              <p className="text-[13px] text-muted">{drafts.length} {drafts.length === 1 ? "draft waits" : "drafts wait"} for your approval.</p>
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
                  <span className="flex min-w-0 flex-col">
                    <span className="font-semibold">
                      {document.parts.length > 0
                        ? document.parts.map((p) => DOCUMENT_NAMES[p.doc_type] ?? p.doc_type).join(", ")
                        : document.status === "failed" ? "Could not be read" : "Being read"}
                    </span>
                    <span className="truncate text-[13px] text-muted" title={document.filename}>{document.filename}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Activity" className="flex flex-col gap-3 rounded-[14px] border border-line bg-surface p-5">
            <h2 className="font-display text-base font-semibold">Activity</h2>
            <ol className="flex flex-col gap-3">
              {activity.slice(0, 12).map((line) => (
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
