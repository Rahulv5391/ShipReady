/** A search box named `q`; pressing Enter submits the form it sits in. */
export function SearchField({ label, placeholder, value }: { label: string; placeholder: string; value: string }) {
  return (
    <label className="flex min-h-11 min-w-[260px] items-center gap-2 rounded-[10px] border border-line bg-surface px-3.5 text-muted shadow-[var(--shadow-card)] transition-[border-color,box-shadow] focus-within:border-primary focus-within:shadow-[0_0_0_3px_var(--focus-ring)]">
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="5" stroke="currentColor" strokeWidth="1.6" />
        <path d="M12 12l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span className="sr-only">{label}</span>
      <input
        name="q"
        type="search"
        defaultValue={value}
        placeholder={placeholder}
        className="w-full bg-transparent text-ink outline-none placeholder:text-muted"
      />
    </label>
  );
}
