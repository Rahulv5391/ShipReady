"use client";

import { useEffect } from "react";

/** Brings the rule named in the address (/rules#VAL-03) into view and marks it. The rules stream
 * in after the browser has looked for the anchor, so it cannot do this itself. */
export function ScrollToRule() {
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    const entry = id ? document.getElementById(id) : null;
    if (!entry) return;
    entry.dataset.current = "true";
    entry.scrollIntoView({ block: "start" });
  }, []);
  return null;
}
