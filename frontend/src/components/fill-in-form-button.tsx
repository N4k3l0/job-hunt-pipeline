"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2, Puzzle, Wand2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useExtensionInstalled } from "@/hooks/use-extension";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api-client";
import { askExtension } from "@/lib/extension";
import type { AutoApplyFill } from "@/lib/types";

/** Opens the company's form with the approved answers filled in, through
 *  the Chrome extension. The user looks it over and presses Submit there. */
export function FillInFormButton({ applicationId, onOpened }: {
  applicationId: string;
  onOpened?: () => void;
}) {
  const installed = useExtensionInstalled();
  const toast = useToast();
  const qc = useQueryClient();
  const [filling, setFilling] = useState(false);

  if (installed === false) {
    return (
      <Link href="/dashboard/extension" className="ds-btn sm">
        <Puzzle className="h-3.5 w-3.5" /> Add the extension
      </Link>
    );
  }

  async function fill() {
    setFilling(true);
    try {
      const details = await api.get<AutoApplyFill>(`/api/v1/auto-apply/${applicationId}/fill`);
      // The extension downloads the resume before opening the form.
      const reply = await askExtension("fill-form", { application: details }, 20000);
      if (!reply) throw new Error("The extension didn't answer. Reload this page and try again.");
      if (reply.error) throw new Error(reply.error);
      toast.success("Opening the form", { description: "Look over the answers, then press Submit on the form." });
      // It shows as sent once the extension sees the form accepted.
      setTimeout(() => qc.invalidateQueries({ queryKey: ["auto-apply"] }), 60_000);
      onOpened?.();
    } catch (e) {
      toast.error("Couldn't fill in the form", { description: e instanceof Error ? e.message : undefined });
    } finally {
      setFilling(false);
    }
  }

  return (
    <button
      type="button"
      className="ds-btn primary sm"
      onClick={(e) => {
        e.preventDefault();
        fill();
      }}
      disabled={filling || installed === null}
    >
      {filling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
      Fill in the form
    </button>
  );
}
