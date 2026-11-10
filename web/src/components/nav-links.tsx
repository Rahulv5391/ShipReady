"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const LINKS: { href: string; label: string; icon: ReactNode }[] = [
  {
    href: "/shipments",
    label: "Shipments",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <rect x="3" y="4" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M3 8h14M7 12h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/shipments/new",
    label: "New shipment",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/rules",
    label: "Rulebook",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M4 4.5A1.5 1.5 0 015.5 3H15v12H5.5A1.5 1.5 0 004 16.5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M4 16.5A1.5 1.5 0 005.5 18H15v-3M7.5 7h4.5M7.5 10h3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/sources",
    label: "Sources",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <ellipse cx="10" cy="5" rx="6" ry="2.5" stroke="currentColor" strokeWidth="1.6" />
        <path d="M4 5v10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5M4 10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
  },
];

/** The sidebar's links, the current page marked. */
export function NavLinks() {
  const pathname = usePathname();
  return <NavList current={pathname} />;
}

/** The same links before the current page is known. */
export function NavList({ current }: { current?: string }) {
  return (
    <nav aria-label="Main" className="order-last flex basis-full gap-1 overflow-x-auto [scrollbar-width:none] side:order-none side:basis-auto side:flex-col side:overflow-visible">
      {LINKS.map((link) => {
        const active = current === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center gap-3 whitespace-nowrap rounded-[10px] px-3 transition-colors ${
              active
                ? "bg-surface font-semibold text-primary shadow-[var(--shadow-raised)]"
                : "text-muted hover:bg-surface/60 hover:text-ink"
            }`}
          >
            <span className="hidden side:block">{link.icon}</span>
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
