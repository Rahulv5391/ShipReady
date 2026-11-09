import type { Metadata } from "next";
import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { api } from "@/lib/api";
import { MODES, READINESS, countryName, progress, timeAgo, type Tone } from "@/lib/format";
import {
  FILTERS,
  matches,
  parseFilter,
  parseSort,
  sortItems,
  type Filter,
  type Sort,
} from "@/lib/queue";
import type { ShipmentListItem } from "@/lib/types";

import { SortSelect } from "./sort-select";

export const metadata: Metadata = { title: "Shipments" };

// The API returns at most 200 a page; the queue shows the newest 200.
const PAGE = 200;
const GRID =
  "grid grid-cols-[minmax(190px,2fr)_minmax(150px,1.4fr)_minmax(150px,1.2fr)_minmax(150px,1.3fr)_128px_116px_76px] gap-3.5";

const TONES: Record<Tone, { fg: string; soft: string }> = {
  fix: { fg: "text-fix", soft: "bg-fix-soft" },
  review: { fg: "text-review", soft: "bg-review-soft" },
  ready: { fg: "text-ready", soft: "bg-ready-soft" },
  running: { fg: "text-primary", soft: "bg-primary-soft" },
  idle: { fg: "text-muted", soft: "bg-sunken" },
};
const DOTS: Record<Tone, string> = {
  fix: "bg-fix",
  review: "bg-review",
  ready: "bg-ready",
  running: "bg-primary shadow-[0_0_0_4px_var(--ring-run)]",
  idle: "bg-idle",
};
const BARS: Record<Tone, string> = {
  fix: "bg-fix",
  review: "bg-review",
  ready: "bg-ready",
  running: "bg-primary",
  idle: "bg-idle",
};
const FILTER_TONES: Record<Filter, Tone> = {
  needs_fix: "fix",
  needs_review: "review",
  ready: "ready",
  active: "running",
};

function ToneIcon({ tone }: { tone: Tone }) {
  const paths: Record<Tone, ReactNode> = {
    fix: <path d="M3.2 3.2l5.6 5.6M8.8 3.2l-5.6 5.6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
    review: (
      <>
        <path d="M6 2.8v3.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <circle cx="6" cy="9" r="1.1" fill="currentColor" />
      </>
    ),
    ready: <path d="M2.6 6.3l2.3 2.3 4.6-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />,
    running: <path d="M6 2.5a3.5 3.5 0 103.5 3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
    idle: null,
  };
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      {paths[tone]}
    </svg>
  );
}

type Params = { q?: string; show?: string; sort?: string };

/** The address for these choices, leaving out what is at its default. */
function href(params: { q: string; show: Filter | null; sort: Sort }): string {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.show) search.set("show", params.show);
  if (params.sort !== "recent") search.set("sort", params.sort);
  const query = search.toString();
  return query ? `/shipments?${query}` : "/shipments";
}

async function Queue({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const q = (params.q ?? "").trim().slice(0, 64);
  const show = parseFilter(params.show);
  const sort = parseSort(params.sort);
  const search = new URLSearchParams({ limit: String(PAGE) });
  if (q) search.set("q", q);
  const all = await api<ShipmentListItem[]>(`/shipments?${search}`);
  const rows = sortItems(all.filter((item) => matches(item, show)), sort);
  const toFix = all.filter((item) => item.readiness === "needs_fix").length;

  return (
    <>
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="font-display text-[34px] font-bold leading-[1.1] tracking-[-0.025em]">Shipments</h1>
          <p className="text-base text-muted">
            {all.length === 0
              ? "Nothing here yet."
              : toFix === 0
                ? "No shipment needs fixing."
                : `${toFix} ${toFix === 1 ? "shipment needs" : "shipments need"} fixing before they can be filed.`}
          </p>
        </div>
        <form action="/shipments" className="ml-auto flex flex-wrap gap-2.5">
          <label className="flex min-h-11 min-w-[260px] items-center gap-2 rounded-[10px] border border-line bg-surface px-3.5 text-muted">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
              <circle cx="8" cy="8" r="5" stroke="currentColor" strokeWidth="1.6" />
              <path d="M12 12l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <span className="sr-only">Search shipments</span>
            <input
              name="q"
              type="search"
              defaultValue={q}
              placeholder="Search by reference"
              className="w-full bg-transparent text-ink outline-none"
            />
          </label>
          {show && <input type="hidden" name="show" value={show} />}
          {sort !== "recent" && <input type="hidden" name="sort" value={sort} />}
        </form>
      </div>

      <div
        role="group"
        aria-label="Filter by readiness"
        className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] overflow-hidden rounded-[14px] border border-line bg-surface"
      >
        {FILTERS.map((filter) => {
          const on = show === filter.id;
          const tone = TONES[FILTER_TONES[filter.id]];
          return (
            <Link
              key={filter.id}
              href={href({ q, show: on ? null : filter.id, sort })}
              aria-pressed={on}
              className={`flex flex-col gap-2.5 border-r border-line px-5 py-[18px] ${on ? tone.soft : ""}`}
            >
              <span className={`flex items-center gap-2 font-semibold ${tone.fg}`}>
                <span className={`grid size-[22px] place-items-center rounded-full ${tone.soft}`}>
                  <ToneIcon tone={FILTER_TONES[filter.id]} />
                </span>
                {filter.label}
              </span>
              <span className="font-display text-4xl font-bold leading-none tracking-[-0.02em] tabular-nums">
                {all.filter((item) => matches(item, filter.id)).length}
              </span>
              <span className="text-[13px] text-muted">{filter.hint}</span>
            </Link>
          );
        })}
      </div>

      <section aria-label="Shipment list" className="overflow-hidden rounded-[14px] border border-line bg-surface">
        <form action="/shipments" className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <h2 className="font-display text-lg font-semibold tracking-[-0.01em]">
            {show ? FILTERS.find((f) => f.id === show)?.label : "All shipments"}
          </h2>
          <span className="text-[13px] text-muted">{rows.length} shown</span>
          {show && (
            <Link href={href({ q, show: null, sort })} className="flex min-h-8 items-center rounded-lg border border-line px-2.5 text-[13px]">
              Clear filter
            </Link>
          )}
          {q && <input type="hidden" name="q" value={q} />}
          {show && <input type="hidden" name="show" value={show} />}
          <label className="ml-auto flex items-center gap-2 text-[13px] text-muted">
            Sort by
            <SortSelect value={sort} />
          </label>
        </form>

        {rows.length === 0 ? (
          <p className="px-5 py-10 text-center text-muted">
            {all.length === 0
              ? q
                ? `No shipment's reference contains "${q}".`
                : "No shipments yet. Add a shipment's documents to check them."
              : "No shipment matches this filter."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[940px]">
              <div className={`${GRID} bg-sunken px-5 py-2.5 text-[13px] font-medium text-muted`}>
                <span>Shipment</span>
                <span>Consignee</span>
                <span>Route</span>
                <span>Progress</span>
                <span>Readiness</span>
                <span>Score</span>
                <span>Updated</span>
              </div>
              {rows.map((item) => (
                <Row key={item.id} item={item} />
              ))}
            </div>
          </div>
        )}
      </section>
    </>
  );
}

function Row({ item }: { item: ShipmentListItem }) {
  const state = progress(item);
  const verdict = item.readiness ? READINESS[item.readiness] : null;
  const score = item.readiness_score === null ? null : Number(item.readiness_score);
  const muted = "text-[13px] text-muted";
  return (
    <div className={`${GRID} items-center border-t border-line px-5 py-3.5`}>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="font-mono text-[13.5px] font-medium text-primary">{item.reference}</span>
        <span className="truncate font-medium">{item.exporter ?? <span className={muted}>Exporter not read yet</span>}</span>
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate">{item.consignee ?? "—"}</span>
        <span className={muted}>{countryName(item.destination_country) ?? ""}</span>
      </span>
      <span className="flex flex-col gap-0.5">
        <span className="flex items-center gap-1.5 font-mono text-[13px]">
          {item.port_of_loading ?? "—"}
          <svg width="14" height="10" viewBox="0 0 14 10" fill="none" aria-label="to">
            <path d="M1 5h11M8.5 1.5L12 5 8.5 8.5" stroke="var(--muted)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {item.port_of_discharge ?? "—"}
        </span>
        <span className={muted}>{item.mode ? MODES[item.mode] : "Mode not set"}</span>
      </span>
      <span className="flex items-start gap-2.5">
        <span className={`mt-[7px] size-2 flex-none rounded-full ${DOTS[state.tone]}`} />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="font-medium">{state.title}</span>
          <span className={`${muted} truncate`} title={state.detail}>{state.detail}</span>
        </span>
      </span>
      <span>
        {verdict ? (
          <span className={`inline-flex items-center gap-1.5 rounded-full py-1 pl-2 pr-[11px] text-[13px] font-semibold ${TONES[verdict.tone].soft} ${TONES[verdict.tone].fg}`}>
            <ToneIcon tone={verdict.tone} />
            {verdict.label}
          </span>
        ) : (
          <span className={muted}>Not checked yet</span>
        )}
      </span>
      <span className="flex items-center gap-2.5">
        <span className="w-[42px] font-display text-base font-semibold tabular-nums">
          {score === null ? "–" : score.toFixed(1)}
        </span>
        <span className="h-1.5 flex-1 overflow-hidden rounded-[3px] bg-track">
          <span
            className={`block h-full rounded-[3px] ${verdict ? BARS[verdict.tone] : ""}`}
            style={{ width: `${score ?? 0}%` }}
          />
        </span>
      </span>
      <span className={muted}>{timeAgo(item.updated_at)}</span>
    </div>
  );
}

function QueueSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading shipments" className="flex flex-col gap-7">
      <div className="h-[72px] w-80 animate-pulse rounded-[14px] bg-surface" />
      <div className="h-[120px] animate-pulse rounded-[14px] bg-surface" />
      <div className="h-[320px] animate-pulse rounded-[14px] bg-surface" />
    </div>
  );
}

export default function ShipmentsPage({ searchParams }: PageProps<"/shipments">) {
  return (
    <>
      <Suspense fallback={<QueueSkeleton />}>
        <Queue searchParams={searchParams as Promise<Params>} />
      </Suspense>
      <p className="text-[13px] text-muted">Readiness is a suggestion. A person marks each shipment ready.</p>
    </>
  );
}
