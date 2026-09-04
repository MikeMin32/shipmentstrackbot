export function StatusPill({ status, label }: { status: string; label: string }) {
  return <span className={`pill status-${status}`}>{label}</span>;
}
