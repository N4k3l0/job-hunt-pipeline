/** How fresh a job is, in words, for job cards.
 *
 *  The age counts from when the company posted the job, or from when the
 *  app found it when there's no posting date (or the "posted" date is later,
 *  which some sources use for "updated"). A job found weeks ago that a job
 *  board still lists says so, so an old date doesn't read as a stale job. */

type Dated = {
  posted_at?: string | null;
  discovered_at?: string | null;
  last_seen_at?: string | null;
};

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

function span(ms: number): { long: string; short: string } {
  const hours = Math.floor(ms / HOUR);
  if (hours < 1) return { long: "just now", short: "now" };
  if (hours < 24) return { long: `${hours} ${hours === 1 ? "hour" : "hours"} ago`, short: `${hours}h` };
  const days = Math.floor(ms / DAY);
  if (days < 14) return { long: `${days} ${days === 1 ? "day" : "days"} ago`, short: `${days}d` };
  const weeks = Math.floor(days / 7);
  return { long: `${weeks} weeks ago`, short: `${weeks}w` };
}

export function jobFreshness(job: Dated, now: number = Date.now()): { long: string; short: string } {
  const found = job.discovered_at ? new Date(job.discovered_at).getTime() : null;
  const posted = job.posted_at ? new Date(job.posted_at).getTime() : null;
  const usePosted = posted != null && (found == null || posted <= found);
  const start = usePosted ? posted : found;
  if (start == null) return { long: "", short: "" };

  const age = span(now - start);
  const verb = usePosted ? "Posted" : "Found";
  let long = age.long === "just now" ? `${verb} just now` : `${verb} ${age.long}`;
  let short = age.short;

  // Only worth saying for jobs that are no longer new.
  const lastSeen = job.last_seen_at ? new Date(job.last_seen_at).getTime() : null;
  if (lastSeen != null && now - start >= 14 * DAY) {
    if (now - lastSeen < 30 * HOUR) {
      long += ", still listed today";
      short += " · listed today";
    } else if (now - lastSeen < 7 * DAY) {
      long += ", still listed this week";
      short += " · listed this week";
    }
  }
  return { long, short };
}
