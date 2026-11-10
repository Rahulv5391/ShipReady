"use client";

import { useActionState } from "react";

import { signIn } from "./actions";

export function SignInForm() {
  const [state, action, pending] = useActionState(signIn, undefined);
  const invalid = state ? true : undefined;
  return (
    <form action={action} className="flex w-full max-w-[380px] flex-col gap-[22px]">
      <div className="flex flex-col gap-1.5">
        <h2 className="page-title">Sign in</h2>
        <p className="text-[15px] text-muted">
          Use your work email to see your organisation&apos;s shipments.
        </p>
      </div>

      {state && (
        <div role="alert" className="flex gap-2.5 rounded-[10px] bg-fix-soft px-3.5 py-3 text-[13.5px] text-fix">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="mt-px flex-none">
            <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
            <path d="M8 4.8v3.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="8" cy="11" r=".9" fill="currentColor" />
          </svg>
          <span>{state.error}</span>
        </div>
      )}

      <div className="flex flex-col gap-[7px]">
        <label htmlFor="email" className="text-[13.5px] font-semibold">Work email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          defaultValue={state?.email}
          aria-invalid={invalid}
          className="field min-h-12 px-3.5 text-[15px]"
        />
      </div>
      <div className="flex flex-col gap-[7px]">
        <div className="flex items-baseline justify-between gap-3">
          <label htmlFor="password" className="text-[13.5px] font-semibold">Password</label>
          <span className="text-[13px] text-muted">Forgot it? Ask your administrator.</span>
        </div>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={invalid}
          className="field min-h-12 px-3.5 text-[15px]"
        />
      </div>
      <label className="flex min-h-7 cursor-pointer items-center gap-2.5 text-sm">
        <input name="remember" type="checkbox" className="size-[18px] accent-primary" />
        Keep me signed in on this device
      </label>

      <button
        type="submit"
        disabled={pending}
        className="btn btn-primary min-h-[50px] text-[15px]"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>

      <p className="border-t border-line pt-[18px] text-[13px] text-muted">
        This showcase uses synthetic shipments only. Can&apos;t sign in? Ask your organisation&apos;s
        administrator.
      </p>
    </form>
  );
}
