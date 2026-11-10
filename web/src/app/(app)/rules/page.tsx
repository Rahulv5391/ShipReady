import type { Metadata } from "next";
import { Suspense } from "react";

import { SearchField } from "@/components/search-field";
import { SeverityChip } from "@/components/tone";
import { api } from "@/lib/api";
import { groupRules, howChecked } from "@/lib/rules";
import type { RuleOut } from "@/lib/types";

import { ScrollToRule } from "./scroll-to-rule";

export const metadata: Metadata = { title: "Rulebook" };

function Rule({ rule }: { rule: RuleOut }) {
  return (
    // The entry a report's rule id links to (/rules#VAL-03) is marked by ScrollToRule.
    <article
      id={rule.id}
      className="grid scroll-mt-6 grid-cols-[72px_minmax(0,1fr)] gap-x-4 border-t border-line px-5 py-4 first:border-t-0 data-[current=true]:bg-primary-soft/60 data-[current=true]:shadow-[inset_3px_0_0_var(--primary)]"
    >
      <span className="pt-0.5 font-mono text-[13px] font-semibold text-ink">{rule.id}</span>
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold leading-snug">{rule.title}</h3>
          <SeverityChip severity={rule.severity} />
        </div>
        <p className="text-[14px] text-muted">{rule.description}</p>
        <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
          <dt className="text-muted">If it fails</dt>
          <dd>{rule.prevents}</dd>
          <dt className="text-muted">Checked by</dt>
          <dd>{howChecked(rule.check_type)}</dd>
          <dt className="text-muted">Basis</dt>
          <dd>{rule.source}</dd>
        </dl>
      </div>
    </article>
  );
}

async function Rulebook({ query }: { query: Promise<string> }) {
  const [rules, q] = await Promise.all([api<RuleOut[]>("/rules"), query]);
  const groups = groupRules(rules, q);
  const blockers = rules.filter((rule) => rule.severity === "blocker").length;
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-[64ch] flex-col gap-1.5">
          <h1 className="page-title">Rulebook</h1>
          <p className="text-muted">
            The {rules.length} checks ShipReady runs on every shipment, and what each code on a report means. A failed
            blocker ({blockers} of them) means the shipment should not be filed.
          </p>
        </div>
        <form action="/rules" className="flex">
          <SearchField label="Search the rulebook" placeholder="Search by code or words" value={q} />
        </form>
      </div>
      {groups.length === 0 ? (
        <p className="card px-5 py-10 text-center text-muted">
          No rule matches &ldquo;{q}&rdquo;. Try a code such as VAL-03, or a word such as container.
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.area} aria-label={group.area} className="flex flex-col gap-3">
            <h2 className="font-display text-lg font-semibold">
              {group.area} <span className="font-sans text-[14px] font-normal text-muted">{group.rules.length}</span>
            </h2>
            <div className="overflow-hidden card">
              {group.rules.map((rule) => (
                <Rule key={rule.id} rule={rule} />
              ))}
            </div>
          </section>
        ))
      )}
      <ScrollToRule />
    </>
  );
}

function RulebookSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the rulebook" className="flex flex-col gap-6">
      <div className="h-[72px] w-2/3 skeleton" />
      <div className="h-[480px] skeleton" />
    </div>
  );
}

export default function RulesPage({ searchParams }: PageProps<"/rules">) {
  // Read inside the boundary: the address is request data, so the frame prerenders without it.
  const query = searchParams.then((s) => (typeof s.q === "string" ? s.q.slice(0, 64) : ""));
  return (
    <Suspense fallback={<RulebookSkeleton />}>
      <Rulebook query={query} />
    </Suspense>
  );
}
