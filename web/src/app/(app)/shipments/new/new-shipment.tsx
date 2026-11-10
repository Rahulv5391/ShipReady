"use client";

import Link from "next/link";
import { useState, type DragEvent } from "react";

import { ACCEPT, MAX_FILE_BYTES, MAX_FILES, accepted, kindOf, sizeText } from "@/lib/documents";
import type { UploadOut } from "@/lib/types";

import { createShipment } from "./actions";
import { DriveButton, type DriveFile } from "./drive-button";
import { Progress, type Uploaded } from "./progress";

type Mode = "sea" | "air";
type Chosen =
  | { key: string; name: string; size: number; from: "computer"; file: File }
  | { key: string; name: string; size: number; from: "drive"; id: string };
type Phase = "choosing" | "uploading" | "processing";

const REQUIRED: Record<Mode, string[]> = {
  sea: ["Commercial invoice", "Packing list", "Shipping bill", "Bill of lading"],
  air: ["Commercial invoice", "Packing list", "Shipping bill", "Airway bill"],
};
const OPTIONAL = ["Purchase order", "Certificate of origin", "LUT acknowledgement"];
const NEXT_STEPS = [
  ["Read", "Every page is read: the text layer, scans and photos with OCR, Excel sheets, Word files."],
  ["Extract", "Each field is copied with where it is printed, so you can see the evidence."],
  ["Check", "The documents are compared with each other and with official reference data."],
  ["You review", "You see what doesn't match, approve the drafted messages and mark it ready."],
];

async function detailOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON: a generic message below.
  }
  return "The upload didn't go through. Try again.";
}

export function NewShipment() {
  const [reference, setReference] = useState("");
  const [mode, setMode] = useState<Mode>("sea");
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [skipped, setSkipped] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ reference: boolean; message: string } | null>(null);
  const [phase, setPhase] = useState<Phase>("choosing");
  const [dragging, setDragging] = useState(false);
  const [shipmentId, setShipmentId] = useState<string | null>(null);
  const [driveToken, setDriveToken] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<Uploaded[]>([]);
  const [duplicates, setDuplicates] = useState<UploadOut["duplicates"]>([]);
  const room = MAX_FILES - chosen.length;

  function addFiles(files: File[]) {
    // The chooser offers only supported types; dropped files are filtered the same way, quietly.
    const fitting = files.filter((file) => accepted(file.name) && file.size <= MAX_FILE_BYTES);
    const taken = fitting.slice(0, room);
    const left = files.length - taken.length;
    setSkipped(
      left === 0
        ? null
        : `${left} ${left === 1 ? "file was" : "files were"} left out: only PDF, Word, Excel, JPEG, PNG or TIFF files up to 25 MB, ${MAX_FILES} at most.`,
    );
    setChosen((current) => [
      ...current,
      ...taken.map((file) => ({
        key: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
        name: file.name,
        size: file.size,
        from: "computer" as const,
        file,
      })),
    ]);
  }

  function addDrive(files: DriveFile[], token: string) {
    setDriveToken(token);
    setChosen((current) => [
      ...current,
      ...files.slice(0, room).map((file) => ({
        key: `drive-${file.id}-${crypto.randomUUID()}`,
        name: file.name,
        size: file.sizeBytes,
        from: "drive" as const,
        id: file.id,
      })),
    ]);
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    addFiles(Array.from(event.dataTransfer.files));
  }

  async function upload() {
    setProblem(null);
    setPhase("uploading");
    let id = shipmentId;
    if (!id) {
      const created = await createShipment(reference, mode);
      if ("error" in created) {
        setProblem({ reference: true, message: created.error });
        setPhase("choosing");
        return;
      }
      id = created.id;
      setShipmentId(id);
    }
    const stored: Uploaded[] = [];
    const repeated: UploadOut["duplicates"] = [];
    const fromComputer = chosen.filter((c) => c.from === "computer");
    const fromDrive = chosen.filter((c) => c.from === "drive");
    try {
      if (fromComputer.length > 0) {
        const form = new FormData();
        for (const item of fromComputer) form.append("files", item.file, item.name);
        const response = await fetch(`/api/shipments/${id}/documents`, { method: "POST", body: form });
        if (!response.ok) throw new Error(await detailOf(response));
        const body = (await response.json()) as UploadOut;
        stored.push(...body.documents.map((d) => ({ id: d.id, filename: d.filename, fromDrive: false })));
        repeated.push(...body.duplicates);
        // These are stored now; a retry sends only what is left.
        setChosen((current) => current.filter((c) => c.from === "drive"));
      }
      if (fromDrive.length > 0) {
        const response = await fetch(`/api/shipments/${id}/documents:import-drive`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ access_token: driveToken, files: fromDrive.map((c) => ({ id: c.id })) }),
        });
        if (!response.ok) throw new Error(await detailOf(response));
        const body = (await response.json()) as UploadOut;
        stored.push(...body.documents.map((d) => ({ id: d.id, filename: d.filename, fromDrive: true })));
        repeated.push(...body.duplicates);
      }
    } catch (error) {
      setUploaded((current) => [...current, ...stored]);
      setDuplicates((current) => [...current, ...repeated]);
      setProblem({
        reference: false,
        message: error instanceof Error ? error.message : "The upload didn't go through. Try again.",
      });
      setPhase("choosing");
      return;
    }
    setUploaded((current) => [...current, ...stored]);
    setDuplicates((current) => [...current, ...repeated]);
    setChosen([]);
    setPhase("processing");
  }

  if (phase === "processing" && shipmentId) {
    return (
      <Progress
        shipmentId={shipmentId}
        reference={reference.trim()}
        uploaded={uploaded}
        duplicates={duplicates}
        onAddMore={() => {
          setDuplicates([]);
          setPhase("choosing");
        }}
      />
    );
  }

  const fromDriveCount = chosen.filter((c) => c.from === "drive").length;
  const busy = phase === "uploading";
  const heading = "flex items-center gap-2.5 font-display text-lg font-semibold";
  const number = "grid size-7 place-items-center rounded-full bg-primary-soft text-sm font-bold text-primary";

  return (
    <div className="flex flex-wrap items-start gap-6">
      <div className="flex min-w-0 flex-[1_1_540px] flex-col gap-6">
        <section aria-label="Shipment details" className="flex flex-col gap-4 card p-6">
          <h2 className={heading}>
            <span className={number}>1</span>
            Shipment details
          </h2>
          <div className="flex flex-wrap gap-5">
            <div className="flex flex-[1_1_240px] flex-col gap-1.5">
              <label htmlFor="reference" className="text-[13.5px] font-semibold">Your reference</label>
              <input
                id="reference"
                value={reference}
                maxLength={64}
                disabled={shipmentId !== null}
                onChange={(event) => {
                  setReference(event.target.value);
                  if (problem?.reference) setProblem(null);
                }}
                placeholder="e.g. SG42-0031"
                aria-invalid={problem?.reference || undefined}
                aria-describedby="reference-hint"
                className="field min-h-12 px-3.5 text-[15px] disabled:opacity-70"
              />
              <span id="reference-hint" className={`text-[13px] ${problem?.reference ? "text-fix" : "text-muted"}`}>
                {problem?.reference ? problem.message : "Must be unique in your organisation."}
              </span>
            </div>
            <fieldset className="flex flex-col gap-1.5" disabled={shipmentId !== null}>
              <legend className="mb-1.5 text-[13.5px] font-semibold">Shipped by</legend>
              <div className="flex gap-2">
                {(["sea", "air"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={mode === option}
                    onClick={() => setMode(option)}
                    className={`btn min-h-12 border px-5 capitalize ${mode === option ? "border-primary bg-primary-soft text-primary" : "border-line-strong hover:bg-sunken"}`}
                  >
                    {option}
                  </button>
                ))}
              </div>
              <span className="text-[13px] text-muted">
                {mode === "sea" ? "Expects a bill of lading." : "Expects an airway bill."}
              </span>
            </fieldset>
          </div>
        </section>

        <section aria-label="Files" className="flex flex-col gap-4 card p-6">
          <h2 className={heading}>
            <span className={number}>2</span>
            Documents
          </h2>
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={drop}
            className={`flex flex-wrap items-center gap-4 rounded-[12px] border-2 border-dashed p-5 transition-colors ${dragging ? "border-primary bg-primary-soft" : "border-line-strong bg-sunken"}`}
          >
            <span className="grid size-12 flex-none place-items-center rounded-full bg-primary-soft text-primary">
              <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
                <path d="M8 19H7a5 5 0 01-.6-9.96A7 7 0 0119.6 8.5 5.5 5.5 0 0120 19h-1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                <path d="M13 22v-9m0 0l-3.5 3.5M13 13l3.5 3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="flex min-w-[200px] flex-1 flex-col gap-0.5">
              <span className="font-semibold">Drop the shipment&apos;s files here</span>
              <span className="text-[13px] text-muted">
                PDF, Word, Excel, JPEG, PNG or TIFF, up to {MAX_FILES} files of 25 MB each. Scans, phone
                photos and several documents in one PDF all work.
              </span>
            </span>
            <span className="flex flex-wrap gap-2.5">
              <label
                htmlFor="files"
                className={`btn btn-md btn-primary ${room === 0 ? "pointer-events-none opacity-50" : ""}`}
              >
                Choose files
              </label>
              <DriveButton room={room} onPicked={addDrive} />
            </span>
            <input
              id="files"
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              onChange={(event) => {
                addFiles(Array.from(event.target.files ?? []));
                event.target.value = ""; // so choosing the same file again still adds it
              }}
            />
          </div>
          {skipped && <p className="text-[13px] text-muted">{skipped}</p>}

          {chosen.length > 0 && (
            <ul aria-label="Chosen files" className="flex flex-col divide-y divide-line rounded-[10px] border border-line">
              {chosen.map((item) => (
                <li key={item.key} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="chip w-14 flex-none bg-sunken text-center text-muted">
                    {kindOf(item.name)}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-medium">{item.name}</span>
                    <span className="text-[13px] text-muted">{item.size ? sizeText(item.size) : "Google Doc or Sheet, converted on upload"}</span>
                  </span>
                  {item.from === "drive" && (
                    <span className="chip bg-primary-soft text-primary">Google Drive</span>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Remove ${item.name}`}
                    onClick={() => setChosen((current) => current.filter((c) => c.key !== item.key))}
                    className="grid size-9 cursor-pointer place-items-center rounded-lg text-muted transition-colors hover:bg-fix-soft hover:text-fix"
                  >
                    <svg width="17" height="17" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                      <path d="M3.5 5h11M7.5 5V3.5h3V5M5 5l.7 9.5h6.6L13 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {problem && !problem.reference && (
            <div role="alert" className="rounded-[10px] bg-fix-soft px-3.5 py-3 text-[13.5px] text-fix">
              {problem.message}
            </div>
          )}
          {uploaded.length > 0 && (
            <p className="text-[13px] text-muted">
              Already uploaded to this shipment: {uploaded.map((u) => u.filename).join(", ")}.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <span className="text-muted">
              {chosen.length === 0 ? (
                "No files chosen yet."
              ) : (
                <>
                  <b className="text-ink">{chosen.length} {chosen.length === 1 ? "file" : "files"} ready</b>
                  {fromDriveCount > 0 && `, ${fromDriveCount} from Google Drive`}.
                </>
              )}
            </span>
            <div className="ml-auto flex gap-2.5">
              <Link href="/shipments" className="btn btn-md text-muted hover:text-ink">
                Cancel
              </Link>
              <button
                type="button"
                onClick={upload}
                disabled={busy || chosen.length === 0 || !reference.trim()}
                className="btn btn-md btn-primary"
              >
                {busy
                  ? "Uploading…"
                  : chosen.length === 0
                    ? "Upload and check"
                    : `Upload and check ${chosen.length} ${chosen.length === 1 ? "file" : "files"}`}
              </button>
            </div>
          </div>
        </section>
      </div>

      <div className="flex flex-[1_1_300px] flex-col gap-5">
        <section aria-label="Documents to include" className="flex flex-col gap-3 card p-5">
          <h2 className="font-display text-base font-semibold">Documents to include</h2>
          <p className="text-[13px] text-muted">A missing required document stops the shipment as a blocker.</p>
          <ul className="flex flex-col gap-2">
            {[...REQUIRED[mode].map((name) => [name, true] as const), ...OPTIONAL.map((name) => [name, false] as const)].map(([name, required]) => (
              <li key={name} className="flex items-center justify-between gap-3">
                <span>{name}</span>
                <span className={`text-[12.5px] font-semibold ${required ? "text-primary" : "text-muted"}`}>
                  {required ? "Required" : "If you have it"}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="What happens next" className="flex flex-col gap-3 card p-5">
          <h2 className="font-display text-base font-semibold">What happens next</h2>
          <ol className="flex flex-col gap-3">
            {NEXT_STEPS.map(([title, text], index) => (
              <li key={title} className="flex gap-3">
                <span className="grid size-6 flex-none place-items-center rounded-full bg-sunken text-[12.5px] font-bold text-muted">{index + 1}</span>
                <span className="flex flex-col">
                  <span className="font-semibold">{title}</span>
                  <span className="text-[13px] text-muted">{text}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
        <p className="flex gap-2 text-[13px] text-muted">
          <svg width="16" height="16" viewBox="0 0 14 14" fill="none" aria-hidden="true" className="mt-0.5 flex-none">
            <rect x="2.5" y="6" width="9" height="6" rx="1" stroke="currentColor" strokeWidth="1.3" />
            <path d="M4.5 6V4.5a2.5 2.5 0 015 0V6" stroke="currentColor" strokeWidth="1.3" />
          </svg>
          <span>Files are stored privately for your organisation. File types are checked from their contents, not their names.</span>
        </p>
      </div>
    </div>
  );
}
