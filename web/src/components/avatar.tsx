import { initials } from "@/lib/report";

/** A person's or a party's initials in a disc. */
export function Avatar({ name }: { name: string }) {
  return (
    <span aria-hidden="true" className="grid size-9 flex-none place-items-center rounded-full bg-primary-soft text-[12.5px] font-bold text-primary">
      {initials(name)}
    </span>
  );
}
