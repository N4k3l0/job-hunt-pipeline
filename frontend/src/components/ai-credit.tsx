"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, Loader2, Wallet } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useAiCredit, useAiStatus, useCurrentUser, useRecordAiCredit } from "@/hooks/use-api";

const money = (value: number | null | undefined) => (value == null ? "" : `$${value.toFixed(2)}`);

function dayLabel(day: string) {
  const date = new Date(`${day}T12:00:00Z`);
  return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function Warning({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-3 text-sm">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
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
      className="mb-4 flex flex-wrap items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-3 text-sm"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
      <span className="min-w-0 flex-1">{data.message}</span>
      <Link href="/dashboard/admin#ai-credit" className="font-medium underline underline-offset-2">
        See spending
      </Link>
    </div>
  );
}

/** Admin: what the app spent on AI each day, what's left, and "I've topped up". */
export function AiCreditCard() {
  const { data, isLoading } = useAiCredit();
  const record = useRecordAiCredit();
  const toast = useToast();
  const [balance, setBalance] = useState("");

  function save(e: React.FormEvent) {
    e.preventDefault();
    const amount = Number(balance);
    if (!balance || Number.isNaN(amount) || amount < 0) {
      toast.error("Type the balance as a number, like 10 or 12.50");
      return;
    }
    record.mutate(amount, {
      onSuccess: () => {
        setBalance("");
        toast.success("Saved. AI is back on", { description: "The app counts down from this balance from now on." });
      },
      onError: (err) => toast.error("Couldn't save it", { description: err.message }),
    });
  }

  const days = [...(data?.days ?? [])].reverse();
  return (
    <Card id="ai-credit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Wallet className="h-5 w-5" />
          AI credit
        </CardTitle>
        <CardDescription>
          What the app spent on Claude this week. These are the app&apos;s own estimates from list prices.
          Anthropic&apos;s console has the exact figure.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !data ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            {data.warning && <Warning text={data.warning} />}
            <p className="text-sm">
              {data.balance ? (
                <>
                  About <strong>{money(Math.max(0, data.left ?? 0))}</strong> left of the{" "}
                  {money(data.balance.amount)} you recorded on {dayLabel(data.balance.recorded_at.slice(0, 10))}.
                  {data.per_day != null && data.days_left != null && (
                    <> At about {money(data.per_day)} a day, that&apos;s about {data.days_left < 1 ? "less than a day" : `${Math.floor(data.days_left)} ${Math.floor(data.days_left) === 1 ? "day" : "days"}`}.</>
                  )}
                </>
              ) : (
                <>
                  After you top up, type the balance from Anthropic&apos;s console below. The app then counts down
                  from it and warns you before it runs out.
                </>
              )}
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
                <span className="text-muted-foreground">Balance on Anthropic&apos;s console ($)</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.01"
                  value={balance}
                  onChange={(e) => setBalance(e.target.value)}
                  placeholder="10.00"
                  className="h-9 w-36 rounded-md border bg-transparent px-3 text-sm"
                  style={{ borderColor: "var(--ds-line-strong)" }}
                />
              </label>
              <Button type="submit" disabled={record.isPending}>
                {record.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                I&apos;ve topped up
              </Button>
            </form>
          </>
        )}
      </CardContent>
    </Card>
  );
}
