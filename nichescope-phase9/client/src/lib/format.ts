export function formatNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatCurrency(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  const code = currency?.trim().toUpperCase();
  if (code === "UNKNOWN") return `${formatNumber(value)} (currency unavailable)`;
  if (code) {
    try {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: code,
        maximumFractionDigits: 2,
      }).format(value);
    } catch {
      return `${formatNumber(value)} ${code}`;
    }
  }
  return formatNumber(value);
}

export function formatDate(value: string | null | undefined, includeTime = false): string {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return new Intl.DateTimeFormat("en-US", includeTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(date);
}

export function scoreTone(score: number): string {
  if (score >= 70) return "score-high";
  if (score >= 40) return "score-mid";
  return "score-low";
}
