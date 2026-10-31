export function formatAuctionGates(gate: string | null | undefined): string {
  if (!gate) return "—";
  return gate
    .split("|")
    .map((part) => part.replace("_", "~"))
    .join(" 或 ");
}
