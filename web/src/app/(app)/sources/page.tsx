import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { api } from "@/lib/api";
import { ruleHref } from "@/lib/rules";
import { dayLabel, rowsLabel, siteOf } from "@/lib/sources";
import type { DatasetOut, RegulationOut, SourcesOut } from "@/lib/types";

export const metadata: Metadata = { title: "Sources" };

function ExternalLink({ url, label }: { url: string; label: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-semibold text-primary hover:underline">
      {label}
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M5 2.5H2.5v7h7V7M7 2.5h2.5V5M9.5 2.5L5.5 6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

/** The checks a source supports, each linking to its rulebook entry. */
function UsedBy({ ids, none }: { ids: string[]; none: string }) {
  if (ids.length === 0) return <span className="text-muted">{none}</span>;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="text-muted">Used by</span>
      {ids.map((id) => (
        <Link key={id} href={ruleHref(id)} className="chip bg-sunken font-mono font-medium text-ink hover:text-primary" title="What this check means">
          {id}
        </Link>
      ))}
    </span>
  );
}

function Dataset({ dataset }: { dataset: DatasetOut }) {
  return (
    <article id={dataset.id} className="grid scroll-mt-6 gap-x-6 gap-y-3 border-t border-line px-5 py-4 first:border-t-0 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="flex min-w-0 flex-col gap-1">
        <h3 className="font-semibold leading-snug">{dataset.title}</h3>
        <p className="text-[14px] text-muted">{dataset.note}</p>
      </div>
      <p className="flex flex-col sm:items-end sm:text-right">
        <span className={`font-semibold tabular-nums ${dataset.rows === 0 ? "text-review" : ""}`}>{rowsLabel(dataset.rows)}</span>
        {dataset.as_of && <span className="text-[13px] text-muted">Newest rate in force from {dayLabel(dataset.as_of)}</span>}
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] sm:col-span-2">
        <span>{dataset.publisher}</span>
        {dataset.url && <ExternalLink url={dataset.url} label={`Open on ${siteOf(dataset.url)}`} />}
        <span className="sm:ml-auto">
          <UsedBy ids={dataset.used_by} none="No check reads it directly" />
        </span>
      </div>
    </article>
  );
}

function Regulation({ regulation }: { regulation: RegulationOut }) {
  return (
    <article id={regulation.id} className="flex scroll-mt-6 flex-col gap-2.5 border-t border-line px-5 py-4 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold leading-snug">{regulation.title}</h3>
        <span className="chip flex-none bg-sunken uppercase text-muted">{regulation.format}</span>
      </div>
      <p className="text-[14px] text-muted">
        {regulation.issuer}. {regulation.version}.
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px]">
        <ExternalLink url={regulation.url} label={`Open on ${siteOf(regulation.url)}`} />
        <span className="sm:ml-auto">
          <UsedBy ids={regulation.used_by} none="Not cited by a check" />
        </span>
      </div>
    </article>
  );
}

async function Sources() {
  const { regulations, datasets } = await api<SourcesOut>("/sources");
  return (
    <>
      <div className="flex max-w-[68ch] flex-col gap-1.5">
        <h1 className="page-title">Sources</h1>
        <p className="text-muted">
          Where ShipReady&apos;s checks get their facts: the official data they compare documents against, and the
          regulations they quote when a check fails. All of it comes from the publishers below, never from copies on
          other sites.
        </p>
      </div>
      <section aria-labelledby="datasets" className="flex flex-col gap-3">
        <div className="flex flex-col gap-0.5">
          <h2 id="datasets" className="font-display text-lg font-semibold">Reference data</h2>
          <p className="text-[13px] text-muted">Downloaded from each publisher and loaded in full; the counts are what is loaded now.</p>
        </div>
        <div className="card overflow-hidden">
          {datasets.map((dataset) => (
            <Dataset key={dataset.id} dataset={dataset} />
          ))}
        </div>
      </section>
      <section aria-labelledby="regulations" className="flex flex-col gap-3">
        <div className="flex flex-col gap-0.5">
          <h2 id="regulations" className="font-display text-lg font-semibold">Regulations</h2>
          <p className="text-[13px] text-muted">The texts a failed check cites, from government sites only.</p>
        </div>
        <div className="card overflow-hidden">
          {regulations.map((regulation) => (
            <Regulation key={regulation.id} regulation={regulation} />
          ))}
        </div>
      </section>
    </>
  );
}

function SourcesSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the sources" className="flex flex-col gap-6">
      <div className="h-[72px] w-2/3 skeleton" />
      <div className="h-[520px] skeleton" />
    </div>
  );
}

export default function SourcesPage() {
  return (
    <Suspense fallback={<SourcesSkeleton />}>
      <Sources />
    </Suspense>
  );
}
