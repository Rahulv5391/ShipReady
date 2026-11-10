import type { ReactNode } from "react";

import type { Tone } from "@/lib/format";
import { SEVERITY_LABELS } from "@/lib/report";
import type { Severity } from "@/lib/types";

/** Colours and icons for the verdicts, states and severities, shared by every page. */

export const TONES: Record<Tone, { fg: string; soft: string; solid: string }> = {
  fix: { fg: "text-fix", soft: "bg-fix-soft", solid: "bg-fix" },
  review: { fg: "text-review", soft: "bg-review-soft", solid: "bg-review" },
  ready: { fg: "text-ready", soft: "bg-ready-soft", solid: "bg-ready" },
  running: { fg: "text-primary", soft: "bg-primary-soft", solid: "bg-primary" },
  idle: { fg: "text-muted", soft: "bg-sunken", solid: "bg-idle" },
};

const PATHS: Record<Tone, ReactNode> = {
  fix: <path d="M3.2 3.2l5.6 5.6M8.8 3.2l-5.6 5.6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  review: (
    <>
      <path d="M6 2.8v3.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <circle cx="6" cy="9" r="1.1" fill="currentColor" />
    </>
  ),
  ready: <path d="M2.6 6.3l2.3 2.3 4.6-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />,
  running: <path d="M6 2.5a3.5 3.5 0 103.5 3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  idle: null,
};

export function ToneIcon({ tone }: { tone: Tone }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      {PATHS[tone]}
    </svg>
  );
}

const SEVERITY_TONES: Record<Severity, string> = {
  blocker: "bg-fix-soft text-fix",
  major: "bg-review-soft text-review",
  minor: "bg-sunken text-muted",
  info: "bg-sunken text-muted",
};

export function SeverityChip({ severity }: { severity: Severity }) {
  return <span className={`chip flex-none ${SEVERITY_TONES[severity]}`}>{SEVERITY_LABELS[severity]}</span>;
}
