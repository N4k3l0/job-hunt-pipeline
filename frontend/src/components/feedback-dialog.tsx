"use client";

/**
 * Inline feedback widget. Lives in the app sidebar so any signed-in
 * user can submit a bug, feature request, or general comment without
 * leaving the dashboard. Sends to /api/v1/feedback which stores
 * against their user_id; admin reads in the admin panel.
 *
 * Auto-attaches lightweight context (current URL, viewport, user-agent
 * basic) to the submission so a triage admin can reproduce easily —
 * nothing more invasive than that. No tracking, no analytics, no
 * fingerprinting.
 */

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Loader2, MessageSquare, CheckCircle2 } from "lucide-react";
import { useSubmitFeedback } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

type Category = "bug" | "feature" | "general";

const CATEGORY_OPTIONS: { value: Category; label: string; hint: string }[] = [
  { value: "bug", label: "Bug", hint: "Something's broken or behaving wrong" },
  { value: "feature", label: "Feature request", hint: "An idea for something new" },
  { value: "general", label: "General", hint: "Comment, complaint, anything else" },
];

export function FeedbackDialog({ trigger }: { trigger: React.ReactElement }) {
  const submit = useSubmitFeedback();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<Category>("general");
  const [message, setMessage] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async () => {
    const trimmed = message.trim();
    if (trimmed.length < 4) {
      toast.error("Add a bit more detail", {
        description: "Even one short sentence helps us understand what you mean.",
      });
      return;
    }
    // Lightweight context only — page URL + viewport + browser. No
    // tracking, no fingerprinting.
    const context =
      typeof window === "undefined"
        ? ""
        : JSON.stringify({
            url: window.location.pathname + window.location.search,
            viewport: `${window.innerWidth}x${window.innerHeight}`,
            ua: navigator.userAgent.slice(0, 200),
          });
    try {
      await submit.mutateAsync({ category, message: trimmed, context });
      setSubmitted(true);
      // Reset after a short delay so the user sees the success state.
      setTimeout(() => {
        setOpen(false);
        setSubmitted(false);
        setMessage("");
        setCategory("general");
      }, 1400);
    } catch (e: any) {
      toast.error("Couldn't send feedback", {
        description: e?.message || "Try again in a moment.",
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger} />
      <DialogContent className="sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            Send feedback
          </DialogTitle>
          <DialogDescription>
            Found a bug, have an idea, or just want to vent? Send it
            here and the admin will see it.
          </DialogDescription>
        </DialogHeader>

        {submitted ? (
          <div className="py-8 text-center space-y-2">
            <CheckCircle2 className="h-10 w-10 text-emerald-400 mx-auto" />
            <p className="text-sm font-medium">Got it — thank you.</p>
            <p className="text-xs text-muted-foreground">
              Admin will see this in the queue.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Category</Label>
              <div className="grid grid-cols-3 gap-2">
                {CATEGORY_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setCategory(opt.value)}
                    className={[
                      "rounded-lg border px-3 py-2.5 text-left transition-colors",
                      category === opt.value
                        ? "border-foreground/60 bg-white/[0.04]"
                        : "border-white/[0.06] hover:border-white/[0.16]",
                    ].join(" ")}
                  >
                    <p className="text-sm font-medium">{opt.label}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5 leading-tight">
                      {opt.hint}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="feedback-message">Message</Label>
              <textarea
                id="feedback-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={6}
                placeholder={
                  category === "bug"
                    ? "What did you do, what did you expect, what happened instead?"
                    : category === "feature"
                      ? "What would you like to be able to do?"
                      : "What's on your mind?"
                }
                className="block w-full resize-y rounded-lg bg-white/[0.02] border border-white/[0.06] focus:border-white/[0.2] focus:outline-none p-3 text-sm leading-relaxed font-sans"
                autoFocus
              />
              <p className="text-[11px] text-muted-foreground">
                We attach the current page URL + your browser type so admin
                can reproduce. No tracking, no analytics.
              </p>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={submit.isPending || message.trim().length < 4}
              >
                {submit.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Sending…</>
                ) : (
                  <>Send</>
                )}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
