"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useReviewQueue } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

/**
 * Mounted once at the dashboard layout level. Watches the review queue (which
 * already polls while items are generating) and fires a toast the first time we
 * see a generating item flip to "ready" or "failed". This lets the user start
 * something tailoring, navigate away, and still hear about completion.
 */
export function QueueWatcher() {
  const { data } = useReviewQueue();
  const toast = useToast();
  const router = useRouter();
  // Track the last known status per id so we only fire on the transition edge.
  const lastStatus = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    if (!data) return;
    const seen = new Set<string>();
    for (const item of data) {
      seen.add(item.id);
      const prev = lastStatus.current.get(item.id);
      const next = item.approval_status;
      if (prev && prev !== next) {
        if (prev === "generating" && next === "ready") {
          toast.success("Your resume for this job is ready", {
            description: item.job?.title
              ? `${item.job.company} — ${item.job.title}`
              : "It's under Applications.",
          });
        } else if (prev === "generating" && next === "failed") {
          toast.error("Couldn't write the resume", {
            description: item.progress_step ?? "Try again from the job's page.",
          });
        }
      }
      lastStatus.current.set(item.id, next);
    }
    // Forget items that left the queue (approved/discarded) so a future re-add
    // can still fire transitions.
    for (const id of Array.from(lastStatus.current.keys())) {
      if (!seen.has(id)) lastStatus.current.delete(id);
    }
  }, [data, toast, router]);

  return null;
}
