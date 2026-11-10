import type { Metadata } from "next";

import { NewShipment } from "./new-shipment";

export const metadata: Metadata = { title: "New shipment" };

export default function NewShipmentPage() {
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <h1 className="page-title">New shipment</h1>
        <p className="max-w-[70ch] text-base text-muted">
          Add every document for one shipment. ShipReady works out which document is which and
          checks them against each other.
        </p>
      </div>
      <NewShipment />
    </>
  );
}
