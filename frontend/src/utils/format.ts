const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(n: number | null | undefined, currency?: string | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (!currency || currency.toUpperCase() === "INR") return INR.format(n);
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currency.toUpperCase(),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
  }
}

export function formatPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 1000) / 10}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function confidenceBand(confidence: number | null | undefined): "High" | "Medium" | "Low" | null {
  if (confidence == null) return null;
  if (confidence >= 0.9) return "High";
  if (confidence >= 0.7) return "Medium";
  return "Low";
}

export function formatConfidence(confidence: number | null | undefined): string | null {
  const band = confidenceBand(confidence);
  if (band == null || confidence == null) return null;
  return `${band} confidence · ${Math.round(confidence * 100)}%`;
}

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "Record";
  const map: Record<string, string> = {
    bank: "Bank",
    processor: "Processor",
    erp: "ERP",
    order: "Order",
    payment: "Payment",
    settlement: "Settlement",
  };
  return map[source.toLowerCase()] || source;
}
