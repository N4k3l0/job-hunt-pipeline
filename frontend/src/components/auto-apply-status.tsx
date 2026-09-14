import type { AutoApplicationStatus } from "@/lib/types";

export const AUTO_APPLY_STATUS_LABELS: Record<AutoApplicationStatus, string> = {
  preparing: "Preparing",
  needs_you: "Needs you",
  queued: "Approved",
  submitting: "Sending",
  submitted: "Sent",
  failed: "Couldn't apply",
  unsupported: "Not supported",
  cancelled: "Stopped",
};

/** The design system uses one accent and no traffic-light colors: the
 *  accent marks what's waiting on the user, everything else is neutral. */
export function AutoApplyStatusPill({ status }: { status: AutoApplicationStatus }) {
  return (
    <span className={`ds-pill${status === "needs_you" ? " accent" : ""}`}>
      {AUTO_APPLY_STATUS_LABELS[status]}
    </span>
  );
}
