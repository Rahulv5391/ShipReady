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
];

/** The sidebar's links, the current page marked. */
export function NavLinks() {
  const pathname = usePathname();
  return <NavList current={pathname} />;
}

/** The same links before the current page is known. */
export function NavList({ current }: { current?: string }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {LINKS.map((link) => {
        const active = current === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center gap-3 rounded-[10px] px-3 ${
              active
                ? "bg-surface font-semibold text-primary shadow-[var(--nav-shadow)]"
                : "text-muted hover:text-ink"
            }`}
          >
            {link.icon}
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
