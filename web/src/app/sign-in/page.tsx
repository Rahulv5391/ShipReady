import type { Metadata } from "next";

import { LogoMark } from "@/components/logo";

import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Sign in" };

/** Two synthetic documents disagreeing on a GSTIN, as ShipReady would catch it. */
function PaperIllustration() {
  const highlight = "bg-[#FFE27A] px-1 font-bold shadow-[0_0_0_2px_#C8372D]";
  return (
    <div aria-hidden="true" className="relative h-[330px] w-full max-w-[520px]">
      <div className="absolute left-0 top-[18px] flex w-[62%] -rotate-4 flex-col gap-2 rounded bg-white px-[18px] pb-[22px] pt-[18px] font-[Arial,sans-serif] text-[10px] text-[#23262B] shadow-[0_18px_40px_rgba(0,0,0,.28)]">
        <span className="border-b-2 border-[#23262B] pb-1.5 text-xs font-bold tracking-[0.06em]">COMMERCIAL INVOICE</span>
        <span className="font-bold">KULKARNI TEXTILES PVT LTD</span>
        <span className="text-[#6B7280]">Ichalkaranji, Maharashtra</span>
        <span>GSTIN <span className={highlight}>27AAPFU0939F1ZV</span></span>
        {["w-4/5", "w-[64%]", "w-[72%]"].map((width) => (
          <span key={width} className={`mt-1.5 block h-1.5 rounded-[3px] bg-[#E5E7EB] ${width}`} />
        ))}
      </div>
      <div className="absolute right-0 top-24 flex w-[60%] rotate-3 flex-col gap-2 rounded bg-[#F3F0E8] px-[18px] pb-[22px] pt-[18px] font-mono text-[10px] text-[#2B2A27] shadow-[0_18px_40px_rgba(0,0,0,.3)]">
        <span className="border-b border-dashed border-[#7A766C] pb-1.5 text-[11.5px] font-bold tracking-[0.06em]">SHIPPING BILL CHECKLIST</span>
        <span>EXPORTER  KULKARNI TEXTILES</span>
        <span>PORT      INNSA1</span>
        <span>GSTIN     <span className={highlight}>27AAPFU0939F1ZW</span></span>
        {["w-[76%]", "w-[58%]"].map((width) => (
          <span key={width} className={`mt-1.5 block h-1.5 rounded-[3px] bg-[#DEDAD0] ${width}`} />
        ))}
      </div>
      <div className="absolute left-[36%] top-[220px] -rotate-9 rounded-[10px] border-[3px] border-[#E0574A] p-1 text-[#E0574A] opacity-90">
        <div className="flex flex-col items-center rounded-[7px] border-[1.5px] border-[#E0574A] px-4 pb-1.5 pt-[7px]">
          <span className="font-display text-2xl font-extrabold leading-none tracking-[0.06em]">NEEDS FIX</span>
          <span className="font-mono text-[9.5px] tracking-[0.08em]">GSTIN MISMATCH</span>
        </div>
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <div className="flex min-h-screen flex-wrap">
      <section
        aria-label="About ShipReady"
        className="flex flex-[1_1_560px] flex-col gap-11 bg-panel px-[clamp(24px,5vw,72px)] py-11 text-[#EAF3F2]"
      >
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-[10px] bg-[#EAF3F2] text-panel">
            <LogoMark />
          </span>
          <span className="font-display text-[21px] font-bold tracking-[-0.02em]">ShipReady</span>
        </div>
        <h1 className="max-w-[13ch] text-balance font-display text-[clamp(36px,4vw,54px)] font-bold leading-[1.04] tracking-[-0.035em]">
          Find the mismatch before customs does.
        </h1>
        <PaperIllustration />
        <p className="mt-auto max-w-[46ch] text-[15px] text-[#B9D3D0]">
          ShipReady reads every document of an export shipment, compares them with each other and
          with official reference data, and shows you exactly where they disagree.
        </p>
      </section>
      <section aria-label="Sign in" className="flex flex-[1_1_440px] items-center justify-center px-6 py-12">
        <SignInForm />
      </section>
    </div>
  );
}
