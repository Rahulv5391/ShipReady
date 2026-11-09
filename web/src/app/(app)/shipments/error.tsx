"use client";

/** The queue could not be loaded, most often because the API is not running. */
export default function QueueError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-[14px] border border-line bg-surface px-6 py-8">
      <h1 className="font-display text-2xl font-bold">The shipments couldn&apos;t be loaded</h1>
      <p className="text-muted">ShipReady&apos;s server didn&apos;t answer. Try again in a moment.</p>
      <button
        type="button"
        onClick={reset}
        className="min-h-10 cursor-pointer rounded-[10px] bg-primary px-4 font-semibold text-primary-ink"
      >
        Try again
      </button>
    </div>
  );
}
