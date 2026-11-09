"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { DRIVE_TYPES, MAX_FILES } from "@/lib/documents";

// Google's picker is a browser-only web component, so it is never rendered on the server.
const DrivePicker = dynamic(
  () => import("@googleworkspace/drive-picker-react").then((m) => m.DrivePicker),
  { ssr: false },
);
const DrivePickerDocsView = dynamic(
  () => import("@googleworkspace/drive-picker-react").then((m) => m.DrivePickerDocsView),
  { ssr: false },
);

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_API_KEY;
const APP_ID = process.env.NEXT_PUBLIC_GOOGLE_APP_ID;

export type DriveFile = { id: string; name: string; sizeBytes: number };

/**
 * "Choose from Google Drive": opens Google's Picker, with access only to the files picked
 * (drive.file). The picks and Google's short-lived token go to `onPicked`; the token is used by
 * ShipReady's server for this upload only (Decision.md D-37).
 */
export function DriveButton({
  room,
  onPicked,
}: {
  room: number;
  onPicked: (files: DriveFile[], token: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<{ value: string; until: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // The token to reopen the picker with, decided when it is opened: Google's, while still valid.
  const [current, setCurrent] = useState<string | undefined>(undefined);
  if (!CLIENT_ID || !API_KEY || !APP_ID) return null; // Drive import is not set up here

  return (
    <>
      <button
        type="button"
        disabled={room === 0}
        onClick={() => {
          setProblem(null);
          setCurrent(token && token.until > Date.now() ? token.value : undefined);
          setOpen(true);
        }}
        className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 font-semibold disabled:cursor-not-allowed disabled:opacity-50"
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
          <path d="M2 5.5A1.5 1.5 0 013.5 4H7l1.5 1.5h6A1.5 1.5 0 0116 7v6.5a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 012 13.5z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M9 13V8.5m0 0L7 10.5M9 8.5l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Choose from Google Drive
      </button>
      {problem && <span className="basis-full text-[13px] text-muted">{problem}</span>}
      {open && (
        <DrivePicker
          client-id={CLIENT_ID}
          developer-key={API_KEY}
          app-id={APP_ID}
          oauth-token={current}
          multiselect
          max-items={Math.min(room, MAX_FILES)}
          title="Choose the shipment's documents"
          onOauthResponse={(event) => {
            const { access_token, expires_in } = event.detail;
            // A minute's margin, so a token is never sent just as it runs out.
            setToken({ value: access_token, until: Date.now() + (Number(expires_in) - 60) * 1000 });
          }}
          onOauthError={() => {
            setProblem("Google didn't give access to Drive. Try again, or choose files from this computer.");
            setOpen(false);
          }}
          onCanceled={() => setOpen(false)}
          onPicked={(event) => {
            setOpen(false);
            const value = current ?? token?.value;
            if (!value) return;
            onPicked(
              event.detail.docs.map((doc: { id: string; name: string; sizeBytes?: number }) => ({
                id: doc.id,
                name: doc.name,
                sizeBytes: Number(doc.sizeBytes ?? 0),
              })),
              value,
            );
          }}
        >
          <DrivePickerDocsView mime-types={DRIVE_TYPES} include-folders="true" select-folder-enabled="false" />
        </DrivePicker>
      )}
    </>
  );
}
