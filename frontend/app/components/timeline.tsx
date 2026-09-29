export type TimelineEvent = { event_id: number; type: string; stage?: string | null; version?: number | null; error_code?: string | null; received_at: string };

export function Timeline({ events }: { events: TimelineEvent[] }) {
  if (!events?.length) return <p className="text-neutral-500">No events yet.</p>;
  return (
    <ul className="max-h-72 overflow-auto text-xs">
      {[...events].reverse().map((e) => (
        <li key={e.event_id} className="flex gap-3 border-b border-neutral-200 py-1.5 last:border-0">
          <span className="w-20 shrink-0 font-mono text-neutral-500">{new Date(e.received_at).toLocaleTimeString()}</span>
          <span>
            <b>{e.type}</b>
            {e.stage ? ` · ${e.stage}` : ""}
            {e.version ? ` · v${e.version}` : ""}
            {e.error_code ? <b> · {e.error_code}</b> : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
