import Link from "next/link";
import { Suspense } from "react";

import { LogoMark } from "@/components/logo";
import { NavLinks, NavList } from "@/components/nav-links";
import { ThemeSwitch } from "@/components/theme-switch";
import { readSession } from "@/lib/session";

/** Who is signed in, with the way out. Reads the session, so it streams in. */
async function SignedIn() {
  const session = await readSession();
  if (!session) return null;
  const initials = session.user.name
    .split(/\s+/)
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div className="flex items-center gap-2.5 p-2">
      <span className="grid size-9 flex-none place-items-center rounded-full bg-primary-soft text-[13px] font-bold text-primary">
        {initials}
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-semibold">{session.user.name}</span>
        <span className="truncate text-xs text-muted">{session.user.email}</span>
      </span>
      <form action="/sign-out" method="post" className="ml-auto">
        <button type="submit" className="cursor-pointer whitespace-nowrap rounded-lg px-2 py-1 text-[13px] text-muted hover:text-ink">
          Sign out
        </button>
      </form>
    </div>
  );
}

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-wrap">
      <aside className="flex max-w-full flex-[1_1_248px] flex-col gap-6 border-r border-line bg-side px-3.5 py-5 md:max-w-[280px]">
        <Link href="/shipments" className="flex items-center gap-2.5 px-2 py-1">
          <span className="grid size-[34px] place-items-center rounded-[9px] bg-primary text-primary-ink">
            <LogoMark />
          </span>
          <span className="font-display text-[19px] font-bold tracking-[-0.02em]">ShipReady</span>
        </Link>
        <Suspense fallback={<NavList />}>
          <NavLinks />
        </Suspense>
        <div className="mt-auto flex flex-col gap-3">
          <ThemeSwitch />
          <Suspense fallback={<div className="h-[52px]" />}>
            <SignedIn />
          </Suspense>
        </div>
      </aside>
      <main className="flex min-w-0 flex-[999_1_640px] flex-col gap-7 px-[clamp(16px,3vw,44px)] pb-14 pt-9">
        {children}
      </main>
    </div>
  );
}
