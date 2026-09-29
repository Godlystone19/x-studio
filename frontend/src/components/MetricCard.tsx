interface MetricCardProps {
  label: string;
  value: string | number;
  detail?: string;
  highlight?: boolean;
}

export function MetricCard({ label, value, detail, highlight = false }: MetricCardProps) {
  return (
    <article className="rounded-xl border border-border bg-surface p-4 shadow-subtle">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className={`mt-2 text-2xl font-mono ${highlight ? 'text-accent' : 'text-foreground'}`}>{value}</p>
      {detail && <p className="mt-1 text-xs text-muted">{detail}</p>}
    </article>
  );
}
