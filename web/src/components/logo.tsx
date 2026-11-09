/** The ShipReady mark: a crate with a tick. */
export function LogoMark({ className = "" }: { className?: string }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true" className={className}>
      <path d="M3.5 6.5h13v9h-13z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M7 6.5V4h6v2.5" stroke="currentColor" strokeWidth="1.7" />
      <path d="M7 11l2.2 2.2L13.5 9" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
