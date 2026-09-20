// `product/foundation/values.py::Money.__str__()` returns
// `f"{self.decimal:.2f} {self.currency}"` -- a single combined string
// (e.g. "1500.00 USD"). The create/update request bodies instead take
// `amount_decimal`/`amount_currency` as two separate fields
// (`product/crm/routes.py::CreateOpportunityRequest`). These two
// functions are the one place that split/join happens, so no component
// re-implements the parse.

export function parseMoney(amount: string | null): { decimal: string; currency: string } | null {
  if (!amount) return null;
  const spaceIndex = amount.lastIndexOf(" ");
  if (spaceIndex === -1) return null;
  return {
    decimal: amount.slice(0, spaceIndex),
    currency: amount.slice(spaceIndex + 1),
  };
}

export function formatMoney(amount: string | null): string {
  if (!amount) return "—";
  return amount;
}
