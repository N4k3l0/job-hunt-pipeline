"use client";

import { useEffect, useRef } from "react";
import { useProfile, useWorkHistory, useAutoSuggestRoles } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

/**
 * One-shot heal for users whose target_roles is empty.
 *
 * Older accounts (parsed before the resume parser started auto-suggesting
 * target_roles) are stuck with target_roles=null forever — the resume
 * parse is idempotent so a re-upload of the same file won't refresh it.
 * Without target_roles the scorer runs both PM and AI paths, and tools
 * like Jira/Linear/Asana inflate AI Engineer matches.
 *
 * Mounted once at the dashboard layout. On first mount per session,
 * checks the user's profile. If target_roles is empty AND there's
 * parsed work_history to infer from, fires a single LLM call to
 * suggest 2-3 canonical roles, persists them, and rescores the inbox.
 *
 * Session-scoped guard avoids re-firing on every navigation.
 */
const SESSION_FLAG = "jhp:roleSuggestChecked";

export function RoleAutoSuggest() {
  const { data: profile, isLoading: profileLoading } = useProfile();
  const { data: workHistory } = useWorkHistory();
  const suggest = useAutoSuggestRoles();
  const toast = useToast();
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current) return;
    if (profileLoading) return;
    if (!profile) return;
    if (typeof window !== "undefined" && sessionStorage.getItem(SESSION_FLAG)) return;

    const hasRoles = Array.isArray(profile.target_roles) && profile.target_roles.length > 0;
    const hasParsedResume = Array.isArray(workHistory) && workHistory.length > 0;
    if (hasRoles || !hasParsedResume) {
      // Either nothing to do, or no source material — set the flag so we
      // don't re-check on every dashboard navigation this session.
      try { sessionStorage.setItem(SESSION_FLAG, "1"); } catch { /* private mode */ }
      return;
    }

    fired.current = true;
    try { sessionStorage.setItem(SESSION_FLAG, "1"); } catch { /* private mode */ }

    suggest.mutate(undefined, {
      onSuccess: (data) => {
        if (data.applied && data.suggested.length > 0) {
          toast.success("Target roles set from your resume", {
            description: `Picked ${data.suggested.join(", ")}. Edit in Profile → Preferences.`,
          });
        }
      },
    });
  }, [profile, profileLoading, workHistory, suggest, toast]);

  return null;
}
