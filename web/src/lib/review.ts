/** Plain words for the API's refusals of a review action (each a 409 with its reason). */
export function reviewError(status: number, detail: string): string {
  if (status === 404) return "This shipment or message no longer exists. Reload the page.";
  if (status === 409) {
    if (detail.startsWith("blocker checks fail")) return "Blocker checks still fail. Give a reason to mark it ready anyway.";
    if (detail === "the shipment is not awaiting review") {
      return "This shipment isn't waiting for review any more. Reload to see where it is.";
    }
    if (detail === "a run of this shipment is in progress") return "It's being checked already.";
    if (detail === "the shipment's files are not all read") return "Some files are still being read. Try again in a moment.";
    if (detail.startsWith("the message is already")) return `This message was ${detail.slice(23)} already. Reload the page.`;
  }
  if (status === 503) return "ShipReady's work queue isn't answering. Try again in a minute.";
  return detail || "That didn't work. Try again.";
}

/** The message as it is copied into an email. */
export function messageText(subject: string, body: string): string {
  return `Subject: ${subject.trim()}\n\n${body.trim()}\n`;
}
