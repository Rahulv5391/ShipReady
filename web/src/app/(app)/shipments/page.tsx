import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SearchField } from "@/components/search-field";
import { ToneIcon, TONES } from "@/components/tone";
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
  "grid grid-cols-[minmax(160px,2fr)_minmax(110px,1.4fr)_minmax(130px,1.1fr)_minmax(130px,1.3fr)_116px_84px_92px] gap-3";

const DOTS: Record<Tone, string> = {
  fix: "bg-fix",
  review: "bg-review",
  ready: "bg-ready",
  running: "bg-primary shadow-[0_0_0_4px_var(--ring-run)]",
  idle: "bg-idle",
};
const FILTER_TONES: Record<Filter, Tone> = {
  needs_fix: "fix",
  needs_review: "review",
  ready: "ready",
  active: "running",
};

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
          <h1 className="page-title">Shipments</h1>
          <p className="text-base text-muted">
            {all.length === 0
              ? "Nothing here yet."
              : toFix === 0
                ? "No shipment needs fixing."
                : `${toFix} ${toFix === 1 ? "shipment needs" : "shipments need"} fixing before they can be filed.`}
          </p>
        </div>
        <form action="/shipments" className="ml-auto flex flex-wrap gap-2.5">
          <SearchField label="Search shipments" placeholder="Search by reference" value={q} />
          {show && <input type="hidden" name="show" value={show} />}
          {sort !== "recent" && <input type="hidden" name="sort" value={sort} />}
          <Link
            href="/shipments/new"
            className="btn btn-md btn-primary"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            New shipment
          </Link>
        </form>
      </div>

      <div
        role="group"
        aria-label="Filter by readiness"
        className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] overflow-hidden card"
      >
        {FILTERS.map((filter) => {
          const on = show === filter.id;
          const tone = TONES[FILTER_TONES[filter.id]];
          return (
            <Link
              key={filter.id}
              href={href({ q, show: on ? null : filter.id, sort })}
              aria-pressed={on}
              className={`relative grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 border-r border-line px-5 py-4 transition-colors last:border-r-0 ${on ? tone.soft : "hover:bg-sunken"}`}
            >
              {on && <span className={`absolute inset-x-0 top-0 h-[3px] ${tone.solid}`} />}
              <span className={`flex items-center gap-2 font-semibold ${tone.fg}`}>
                <span className={`grid size-[22px] place-items-center rounded-full ${tone.soft}`}>
                  <ToneIcon tone={FILTER_TONES[filter.id]} />
                </span>
                {filter.label}
              </span>
              <span className="row-span-2 font-display text-[34px] font-bold leading-none tracking-[-0.02em] tabular-nums">
                {all.filter((item) => matches(item, filter.id)).length}
              </span>
              <span className="text-[13px] text-muted">{filter.hint}</span>
            </Link>
          );
        })}
      </div>

      <section aria-label="Shipment list" className="overflow-hidden card">
        <form action="/shipments" className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <h2 className="font-display text-lg font-semibold tracking-[-0.01em]">
            {show ? FILTERS.find((f) => f.id === show)?.label : "All shipments"}
          </h2>
          <span className="text-[13px] text-muted">{rows.length} shown</span>
          {show && (
            <Link href={href({ q, show: null, sort })} className="flex min-h-8 items-center rounded-lg border border-line px-2.5 text-[13px] transition-colors hover:bg-sunken">
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
            <div className="min-w-[934px]">
              <div className={`${GRID} border-b border-line bg-sunken px-5 py-2.5 text-[12.5px] font-semibold text-muted`}>
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
    <div className={`${GRID} relative items-center border-b border-line px-5 py-3.5 transition-colors last:border-b-0 hover:bg-sunken`}>
      <span className="flex min-w-0 flex-col gap-0.5">
        {/* The link covers its row, so a click anywhere on the row opens the report. */}
        <Link href={`/shipments/${item.id}`} className="font-mono text-[13.5px] font-medium text-primary after:absolute after:inset-0 hover:underline">
          {item.reference}
        </Link>
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
          <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full py-1 pl-2 pr-[11px] text-[13px] font-semibold ${TONES[verdict.tone].soft} ${TONES[verdict.tone].fg}`}>
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
            className={`block h-full rounded-[3px] ${verdict ? TONES[verdict.tone].solid : ""}`}
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
      <div className="h-[72px] w-80 skeleton" />
      <div className="h-[84px] skeleton" />
      <div className="h-[320px] skeleton" />
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
