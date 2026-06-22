export default function StatusPill({ status }: { status?: string | null }) {
  const value = status || "idle";
  return <span className={`status-pill status-${value}`}>{value}</span>;
}
