import { Clock } from "lucide-react";

/** Shown on a job the user has worked on that no job site has listed for a
 *  while. The note comes from the API (services/job_freshness.py). */
export function ClosedNote({ note, compact = false }: { note: string; compact?: boolean }) {
  if (compact) {
    return (
      <span className="text-amber-500" title={note} style={{ fontSize: 11, whiteSpace: "nowrap" }}>
        May have closed
      </span>
    );
  }
  return (
    <div className="flex items-start gap-1.5 text-amber-500" style={{ fontSize: 12.5, marginTop: 6 }}>
      <Clock className="h-3.5 w-3.5 shrink-0" style={{ marginTop: 2 }} />
      <span>{note}</span>
    </div>
  );
}
