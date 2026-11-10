import Link from "next/link";
import { Suspense } from "react";

import { Avatar } from "@/components/avatar";
import { LogoMark } from "@/components/logo";
import { NavLinks, NavList } from "@/components/nav-links";
import { ThemeSwitch } from "@/components/theme-switch";
import { readSession } from "@/lib/session";

/** Who is signed in, with the way out. Reads the session, so it streams in. */
async function SignedIn() {
  const session = await readSession();
  if (!session) return null;
  return (
    <div className="flex items-center gap-2.5 side:border-t side:border-line side:px-2 side:pt-3">
      <span className="hidden side:contents">
        <Avatar name={session.user.name} />
      </span>
      <span className="hidden min-w-0 flex-col side:flex">
        <span className="truncate font-semibold">{session.user.name}</span>
        <span className="truncate text-xs text-muted">{session.user.email}</span>
      </span>
      <form action="/sign-out" method="post" className="ml-auto">
        <button type="submit" className="cursor-pointer whitespace-nowrap rounded-lg px-2 py-1 text-[13px] text-muted transition-colors hover:bg-surface hover:text-ink">
          Sign out
        </button>
      </form>
    </div>
  );
}

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-wrap content-start">
      {/* A bar across the top on a narrow screen, so the page starts on the first screen. From the
          `side` width it is a sidebar pinned to the screen, so the theme switch and sign-out stay
          in view while the page scrolls. */}
      <aside className="flex min-w-0 basis-full flex-wrap items-center gap-x-2 gap-y-2 border-b border-line bg-side px-3 py-3 side:sticky side:top-0 side:h-screen side:basis-[248px] side:flex-col side:flex-nowrap side:items-stretch side:gap-6 side:overflow-y-auto side:border-b-0 side:border-r side:px-3.5 side:py-5">
        <Link href="/shipments" className="flex items-center gap-2.5 px-1 py-1 side:px-2">
          <span className="grid size-[34px] place-items-center rounded-[9px] bg-primary text-primary-ink shadow-[var(--shadow-raised)]">
            <LogoMark />
          </span>
          <span className="font-display text-[19px] font-bold tracking-[-0.02em]">ShipReady</span>
        </Link>
        <Suspense fallback={<NavList />}>
          <NavLinks />
        </Suspense>
        <div className="ml-auto flex items-center gap-1 side:ml-0 side:mt-auto side:flex-col side:items-stretch side:gap-3">
          <ThemeSwitch />
          <Suspense fallback={<div className="hidden h-[49px] side:block" />}>
            <SignedIn />
          </Suspense>
        </div>
      </aside>
      <main className="min-w-0 flex-[999_1_640px] px-[clamp(16px,3vw,44px)] pb-14 pt-9">
        {/* Capped so a wide screen does not stretch tables and text past a readable width. */}
        <div className="flex max-w-[1320px] flex-col gap-7">{children}</div>
      </main>
    </div>
  );
}
