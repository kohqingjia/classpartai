export { cn } from "cn";

/** Keeps log lines traceable without writing a full address to stdout. */
export function maskEmail(address: string): string {
  const [local, domain] = address.split("@");
  return `${local.slice(0, 1)}***@${domain}`;
}
