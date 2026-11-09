import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ApiError, api } from "@/lib/api";
import { TEXT_SOURCES, neighbours, parseView, printedDiffers, sheetsFor, type Sheet } from "@/lib/evidence";
import { SEVERITY_LABELS, fieldLabel } from "@/lib/report";
import type { CheckOut, FieldOut, PageOut, ShipmentDetail } from "@/lib/types";

export const metadata: Metadata = { title: "Evidence" };

// When a page's size is unknown: A4 at 150 dpi, the size pages are rendered at.
const A4 = { width: 1241, height: 1754 };

type Query = { view?: string; all?: string };

async function load(id: string, rule: string) {
  try {
    const [shipment, checks, fields] = await Promise.all([
      api<ShipmentDetail>(`/shipments/${id}`),
      api<CheckOut[]>(`/shipments/${id}/checks`),
      api<FieldOut[]>(`/shipments/${id}/fields`),
    ]);
    const check = checks.find((c) => c.rule_id === rule);
    if (!check) notFound();
    const documents = [...new Set(check.evidence.map((f) => f.document_id))];
    const pages = new Map<string, PageOut>();
    for (const [documentId, list] of await Promise.all(
      documents.map(async (d) => [d, await api<PageOut[]>(`/documents/${d}/pages`)] as const),
    )) {
      for (const page of list) pages.set(`${documentId}:${page.page_no}`, page);
    }
    return { shipment, checks, check, fields, pages };
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) notFound();
    throw error;
  }
}

function Marks({ sheet }: { sheet: Sheet }) {
  return sheet.marks.map(({ n, field }) =>
    field.box ? (
      <span
        key={`${field.path}-${n}`}
        title={`${fieldLabel(field.path)}: ${field.value}`}
        // Page images are white paper in either theme, so marks on them keep the light theme's red.
        className={
          n === null
            ? "absolute rounded-[3px] border border-dashed border-primary/70"
            : "absolute rounded-[4px] border-2 border-[#b42f25]"
        }
        // A few pixels around the words, so the outline frames the text instead of crossing it.
        style={{
          left: `calc(${field.box.x0 * 100}% - 4px)`,
          top: `calc(${field.box.y0 * 100}% - 3px)`,
          width: `calc(${(field.box.x1 - field.box.x0) * 100}% + 8px)`,
          height: `calc(${(field.box.y1 - field.box.y0) * 100}% + 6px)`,
        }}
      >
        {n !== null && (
          <>
            <span className="absolute inset-0 bg-[#ffe27a]/45 mix-blend-multiply" />
            <span className="absolute -left-3 -top-3 grid size-5 place-items-center rounded-full bg-[#b42f25] text-[11px] font-bold text-white">
              {n}
            </span>
          </>
        )}
      </span>
    ) : null,
  );
}

function PageView({ sheet, page, filename }: { sheet: Sheet; page: PageOut | undefined; filename: string }) {
  const source = page ? TEXT_SOURCES[page.text_source] : "Not read yet";
  return (
    <figure className="flex min-w-0 flex-[1_1_280px] flex-col gap-2">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 text-[13px]">
        <span className="font-semibold">{sheet.label}</span>
        <span className="text-muted" title={filename}>
          {source}, {filename}
        </span>
      </figcaption>
      {page?.has_image ? (
        <div className="relative overflow-visible rounded-md bg-white shadow-[0_1px_3px_rgba(0,0,0,.18)]">
          <Image
            src={`/api/documents/${sheet.documentId}/pages/${sheet.pageNo}/image`}
            alt={`${sheet.label}, as uploaded`}
            width={page.width_px ?? A4.width}
            height={page.height_px ?? A4.height}
            unoptimized
            className="h-auto w-full rounded-md"
          />
          <Marks sheet={sheet} />
        </div>
      ) : (
        // A spreadsheet has no picture of its page: show the cells' values instead.
        <ol className="flex flex-col gap-1.5 rounded-md bg-surface p-4">
          {sheet.marks.map(({ n, field }) => (
            <li key={`${field.path}-${n}`} className="flex items-baseline gap-2 text-[13px]">
              <span className={`grid size-5 flex-none place-items-center rounded-full text-[11px] font-bold ${n === null ? "bg-sunken text-muted" : "bg-fix text-surface"}`}>
                {n ?? "·"}
              </span>
              <span className="text-muted">{field.path.split(".").slice(1).join(".")}</span>
              <span className="font-mono">{field.value}</span>
            </li>
          ))}
        </ol>
      )}
    </figure>
  );
}

async function Evidence({ ids, query }: { ids: Promise<{ id: string; rule: string }>; query: Promise<Query> }) {
  const [{ id, rule }, { view, all }] = await Promise.all([ids, query]);
  const { shipment, checks, check, fields, pages } = await load(id, decodeURIComponent(rule));
  const outlineAll = all === "1";
  const sheets = sheetsFor(check, outlineAll ? fields : []);
  const shown = parseView(view, sheets.length);
  const place = neighbours(checks, check.rule_id);
  const filenames = new Map(shipment.documents.map((d) => [d.id, d.filename]));
  const base = `/shipments/${id}/checks/${encodeURIComponent(check.rule_id)}`;
  const href = (next: Query) => {
    const params = new URLSearchParams(Object.entries(next).filter((e): e is [string, string] => Boolean(e[1])));
    return params.size ? `${base}?${params}` : base;
  };
  const serious = check.outcome !== "fail" ? "text-review" : check.severity === "blocker" ? "text-fix" : "text-review";

  return (
    <>
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
        <Link href="/shipments" className="hover:text-ink">Shipments</Link>
        <span aria-hidden="true">/</span>
        <Link href={`/shipments/${id}`} className="font-mono hover:text-ink">{shipment.reference}</Link>
        <span aria-hidden="true">/</span>
        <span className="text-ink">{check.title}</span>
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="text-balance font-display text-[26px] font-bold leading-[1.2] tracking-[-0.02em]">{check.title}</h1>
          {check.message && <p className="text-[15px]">{check.message}</p>}
          <p className="text-muted">
            <span className={`font-semibold ${serious}`}>
              {check.outcome === "not_verified" ? "To confirm" : SEVERITY_LABELS[check.severity]}
            </span>
            , check <span className="font-mono text-ink">{check.rule_id}</span>
            {place ? `. Finding ${place.position} of ${place.total}.` : "."}
          </p>
        </div>
        {place && (
          <div className="flex gap-2">
            {[
              ["Previous", place.previous],
              ["Next", place.next],
            ].map(([label, target]) =>
              target ? (
                <Link key={label} href={`/shipments/${id}/checks/${encodeURIComponent(target)}`} className="rounded-[10px] border border-line-strong bg-surface px-3.5 py-2 text-[13.5px] font-semibold hover:bg-sunken">
                  {label}
                </Link>
              ) : (
                <span key={label} aria-disabled="true" className="rounded-[10px] border border-line px-3.5 py-2 text-[13.5px] font-semibold text-muted opacity-60">
                  {label}
                </span>
              ),
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <section aria-label="Pages" className="flex min-w-0 flex-[1_1_640px] flex-col gap-3 rounded-[14px] border border-line bg-viewer p-4">
          {sheets.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              {sheets.length > 1 && (
                <div role="tablist" aria-label="Pages to show" className="flex flex-wrap rounded-[10px] bg-surface/60 p-[3px]">
                  {[{ n: null, label: "Side by side" }, ...sheets.map((s, i) => ({ n: i + 1, label: s.label }))].map((tab) => (
                    <Link
                      key={tab.label}
                      href={href({ view: tab.n ? String(tab.n) : undefined, all })}
                      role="tab"
                      aria-selected={shown === tab.n}
                      scroll={false}
                      className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold ${shown === tab.n ? "bg-surface text-ink shadow-[0_1px_2px_rgba(26,31,43,.08)]" : "text-muted"}`}
                    >
                      {tab.label}
                    </Link>
                  ))}
                </div>
              )}
              <Link
                href={href({ view, all: outlineAll ? undefined : "1" })}
                role="switch"
                aria-checked={outlineAll}
                scroll={false}
                className="ml-auto flex items-center gap-2 text-[13px] font-medium"
              >
                <span className={`flex h-5 w-9 items-center rounded-full p-0.5 ${outlineAll ? "justify-end bg-primary" : "bg-line-strong"}`}>
                  <span className="size-4 rounded-full bg-white" />
                </span>
                Outline every value read
              </Link>
            </div>
          )}
          {sheets.length === 0 ? (
            <p className="px-2 py-16 text-center text-muted">
              This check didn&rsquo;t read a value from the pages.
            </p>
          ) : (
            <div className="flex flex-wrap gap-5">
              {sheets
                .filter((_, i) => shown === null || shown === i + 1)
                .map((sheet) => (
                  <PageView key={sheet.key} sheet={sheet} page={pages.get(sheet.key)} filename={filenames.get(sheet.documentId) ?? ""} />
                ))}
            </div>
          )}
        </section>

        <section aria-label="What the check read" className="flex min-w-0 flex-[1_1_300px] flex-col gap-4 rounded-[14px] border border-line bg-surface p-5">
          <h2 className="font-display text-lg font-semibold">{check.outcome === "pass" ? "What the check read" : "What doesn't match"}</h2>
          {check.evidence.length > 0 && (
            <ol className="flex flex-col gap-3">
              {check.evidence.map((field, index) => (
                <li key={`${field.document_id}-${field.path}`} className="flex gap-2.5">
                  <span className="grid size-6 flex-none place-items-center rounded-full bg-fix text-[12px] font-bold text-surface">{index + 1}</span>
                  <span className="flex min-w-0 flex-col">
                    <span className="text-[13px] font-semibold">{fieldLabel(field.path)}</span>
                    <span className="break-words font-mono text-[14px]">{field.value}</span>
                    {printedDiffers(field.value, field.quote) && (
                      <span className="text-[12.5px] text-muted">Printed as “{field.quote}”</span>
                    )}
                    {!field.box && <span className="text-[12.5px] text-review">Not found on the page image</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {check.critic_reason && (
            <p className={`rounded-lg px-3.5 py-2.5 text-[13.5px] ${check.verification === "misread" ? "bg-review-soft" : "bg-sunken"}`}>
              <b>{check.verification === "misread" ? "Looks like a misreading." : "Re-read and confirmed."}</b> {check.critic_reason}
            </p>
          )}
          {check.citations.map((citation) => (
            <figure key={citation.source_id} className="flex flex-col gap-1 border-t border-line pt-3">
              <span className="text-[13px] font-semibold">Why it matters</span>
              <blockquote className="line-clamp-6 text-[13px] text-muted">{citation.text}</blockquote>
              <figcaption className="text-[12.5px] font-semibold">
                <a href={citation.url} target="_blank" rel="noreferrer" className="hover:underline">
                  {citation.title}
                  {citation.page ? `, page ${citation.page}` : ""}
                </a>
              </figcaption>
            </figure>
          ))}
          <Link href={`/shipments/${id}`} className="text-[13.5px] font-semibold text-primary hover:underline">
            Back to the report
          </Link>
        </section>
      </div>
    </>
  );
}

function EvidenceSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the pages" className="flex flex-col gap-6">
      <div className="h-[64px] w-2/3 animate-pulse rounded-[14px] bg-surface" />
      <div className="h-[640px] animate-pulse rounded-[14px] bg-surface" />
    </div>
  );
}

export default function EvidencePage({ params, searchParams }: PageProps<"/shipments/[id]/checks/[rule]">) {
  const query = searchParams.then((s) => ({
    view: typeof s.view === "string" ? s.view : undefined,
    all: typeof s.all === "string" ? s.all : undefined,
  }));
  return (
    <Suspense fallback={<EvidenceSkeleton />}>
      <Evidence ids={params} query={query} />
    </Suspense>
  );
}
