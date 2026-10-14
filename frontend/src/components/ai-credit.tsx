"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, Loader2, Wallet } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useAiCredit, useAiStatus, useCurrentUser, useSetAiBudget, useTurnAiOn } from "@/hooks/use-api";

const money = (value: number | null | undefined) => (value == null ? "" : `$${value.toFixed(2)}`);

function dayLabel(day: string) {
  const date = new Date(`${day}T12:00:00Z`);
  return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function Warning({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded-lg border border-amber-400/40 bg-warn/10 px-4 py-3 text-sm">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
      <span>{text}</span>
    </div>
  );
}

/** For admins, on every page: the AI is paused, or the credit is nearly gone. */
export function AiCreditBanner() {
  const { data: me } = useCurrentUser();
  const { data } = useAiStatus(me?.role === "admin");
  if (!data?.message || !(data.paused || data.low)) return null;
  return (
    <div
      role="status"
      className="mb-4 flex flex-wrap items-start gap-2 rounded-lg border border-amber-400/40 bg-warn/10 px-4 py-3 text-sm"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
      <span className="min-w-0 flex-1">{data.message}</span>
      <Link href="/dashboard/admin#ai-credit" className="font-medium underline underline-offset-2">
        See spending
      </Link>
    </div>
  );
}

/** Admin: what Job Hunt spent on AI each day, this month against its
 *  budget, changing the budget, and turning AI back on after a top-up. */
export function AiCreditCard() {
  const { data, isLoading } = useAiCredit();
  const setBudget = useSetAiBudget();
  const turnOn = useTurnAiOn();
  const toast = useToast();
  const [budget, setBudgetText] = useState("");

  function save(e: React.FormEvent) {
    e.preventDefault();
    const amount = Number(budget);
    if (!budget || Number.isNaN(amount) || amount <= 0) {
      toast.error("Type the budget as a number, like 15 or 20");
      return;
    }
    setBudget.mutate(amount, {
      onSuccess: () => {
        setBudgetText("");
        toast.success(`Budget set to ${money(amount)} a month`);
      },
      onError: (err) => toast.error("Couldn't save it", { description: err.message }),
    });
  }

  function aiOn() {
    turnOn.mutate(undefined, {
      onSuccess: () => toast.success("AI is back on"),
      onError: (err) => toast.error("Couldn't turn it on", { description: err.message }),
    });
  }

  const days = [...(data?.days ?? [])].reverse();
  return (
    <Card id="ai-credit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Wallet className="h-5 w-5" />
          AI spending
        </CardTitle>
        <CardDescription>
          What Job Hunt spent on Claude, counted from its own calls at list prices. Other products sharing your
          Anthropic account aren&apos;t counted. Anthropic&apos;s console has the exact figures.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !data ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            {data.warning && <Warning text={data.warning} />}
            <p className="text-sm">
              This month: <strong>{money(data.spent_this_month)}</strong> of the {money(data.budget)} budget.
              {data.per_day != null && (
                <> At about {money(data.per_day)} a day, the month is heading for about {money(data.heading_for)}.</>
              )}{" "}
              At the budget, reading new jobs and preparing applications by itself wait for the 1st. What you ask for
              still works.
            </p>

            <div className="divide-y divide-[var(--ds-line)] text-sm">
              {days.map((d) => (
                <div key={d.day} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                  <span className="w-28 shrink-0 text-muted-foreground">{dayLabel(d.day)}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                    {d.tasks.slice(0, 3).map((t) => `${t.name} ${money(t.cost)}`).join(" · ") || "Nothing"}
                  </span>
                  <span className="ds-mono">{money(d.total)}</span>
                </div>
              ))}
            </div>

            <form onSubmit={save} className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Monthly budget for Job Hunt ($)</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min={1}
                  step="1"
                  value={budget}
                  onChange={(e) => setBudgetText(e.target.value)}
                  placeholder={String(data.budget)}
                  className="h-9 w-36 rounded-md border bg-transparent px-3 text-sm"
                  style={{ borderColor: "var(--ds-line-strong)" }}
                />
              </label>
              <Button type="submit" variant="outline" disabled={setBudget.isPending}>
                {setBudget.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save budget
              </Button>
            </form>

            {data.paused && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Topped up your Anthropic account?</span>
                <Button size="sm" onClick={aiOn} disabled={turnOn.isPending}>
                  {turnOn.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Turn AI back on now
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
