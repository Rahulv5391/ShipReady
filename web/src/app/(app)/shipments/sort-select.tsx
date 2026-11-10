"use client";

import { SORTS, type Sort } from "@/lib/queue";

/** The sort order; choosing one submits its form, so the list reloads sorted. */
export function SortSelect({ value }: { value: Sort }) {
  return (
    <select
      name="sort"
      defaultValue={value}
      onChange={(event) => event.currentTarget.form?.requestSubmit()}
      className="min-h-9 cursor-pointer rounded-lg border border-line bg-surface px-2.5 text-ink transition-colors hover:border-line-strong"
    >
      {Object.entries(SORTS).map(([key, label]) => (
        <option key={key} value={key}>
          {label}
        </option>
      ))}
    </select>
  );
}
