import Link from "next/link";
import { Fragment } from "react";

export type Crumb = { label: string; href?: string; mono?: boolean };

/** Where the page sits: each earlier step links back, the last names the page itself. */
export function Breadcrumb({ trail }: { trail: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
      {trail.map((crumb, index) => (
        <Fragment key={crumb.label}>
          {index > 0 && (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M5.5 3.5L9 7l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
          {crumb.href ? (
            <Link href={crumb.href} className={`hover:text-ink ${crumb.mono ? "font-mono" : ""}`}>
              {crumb.label}
            </Link>
          ) : (
            <span aria-current="page" className={`text-ink ${crumb.mono ? "font-mono" : ""}`}>
              {crumb.label}
            </span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
