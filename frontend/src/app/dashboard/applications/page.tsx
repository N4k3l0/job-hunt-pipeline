"use client";

import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronDown, Bell, Loader2, Send, Briefcase } from "lucide-react";
import { useApplicationPipeline, useUpdateStatus, useReminders } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { EmptyState } from "@/components/ui/empty-state";

/** Format a date string ("YYYY-MM-DD") relative to today: "Today",
 *  "Tomorrow", "in 3 days", "3 days ago". Empty input returns null.
 */
function relativeDate(input: string | null | undefined): { text: string; tone: "due" | "soon" | "past" | "neutral" } | null {
  if (!input) return null;
  const target = new Date(input + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const ms = target.getTime() - today.getTime();
  const days = Math.round(ms / (1000 * 60 * 60 * 24));
  if (days === 0) return { text: "Today", tone: "due" };
  if (days === 1) return { text: "Tomorrow", tone: "soon" };
  if (days === -1) return { text: "Yesterday", tone: "past" };
  if (days > 0 && days <= 7) return { text: `in ${days} days`, tone: "soon" };
  if (days < 0) return { text: `${Math.abs(days)} days ago`, tone: "past" };
  return { text: target.toLocaleDateString(undefined, { month: "short", day: "numeric" }), tone: "neutral" };
}

const STATUS_COLORS: Record<string, string> = {
  approved: "bg-blue-500/10 text-blue-400",
  applied: "bg-emerald-500/10 text-emerald-400",
  follow_up_due: "bg-amber-500/10 text-amber-400",
  interviewing: "bg-violet-500/10 text-violet-400",
  offered: "bg-emerald-600/10 text-emerald-400",
  rejected: "bg-red-500/10 text-red-400",
  ghosted: "bg-white/5 text-muted-foreground",
  archived: "bg-white/5 text-muted-foreground",
};

const STATUS_LABELS: Record<string, string> = {
  approved: "Approved",
  applied: "Applied",
  follow_up_due: "Follow-up Due",
  interviewing: "Interviewing",
  offered: "Offered",
  rejected: "Rejected",
  ghosted: "Ghosted",
  archived: "Archived",
};

const STATUS_DOTS: Record<string, string> = {
  follow_up_due: "bg-amber-500",
  interviewing: "bg-violet-500",
  applied: "bg-emerald-500",
  approved: "bg-blue-500",
  offered: "bg-emerald-600",
  rejected: "bg-red-500",
  ghosted: "bg-white/20",
  archived: "bg-white/10",
};

const STATUS_ORDER = ["follow_up_due", "interviewing", "approved", "applied", "offered", "rejected", "ghosted", "archived"];

export default function ApplicationsPage() {
  const { data: tracking, isLoading } = useApplicationPipeline();
  const { data: reminders } = useReminders();
  const updateStatus = useUpdateStatus();
  const toast = useToast();

  const items = tracking ?? [];
  const reminderCount = reminders?.length ?? 0;

  const changeStatus = (id: string, status: string, item: any) => {
    updateStatus.mutate(
      { id, status },
      {
        onSuccess: () =>
          toast.success(`Marked as ${STATUS_LABELS[status] ?? status}`, {
            description: item.job?.title ? `${item.job.company} — ${item.job.title}` : undefined,
          }),
        onError: (err: any) => toast.error("Status update failed", { description: err?.message }),
      },
    );
  };

  const grouped = STATUS_ORDER.reduce((acc, status) => {
    const statusItems = items.filter((t: any) => t.status === status);
    if (statusItems.length > 0) acc.push({ status, items: statusItems });
    return acc;
  }, [] as { status: string; items: any[] }[]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Applications</h1>
          <p className="text-muted-foreground">{items.length} tracked</p>
        </div>
        {reminderCount > 0 && (
          <Button variant="outline" size="sm">
            <Bell className="h-3.5 w-3.5" />
            {reminderCount} follow-up{reminderCount !== 1 ? "s" : ""} due
          </Button>
        )}
      </div>

      {/* Pipeline summary */}
      <div className="flex gap-2 flex-wrap">
        {STATUS_ORDER.map((status) => {
          const count = items.filter((t: any) => t.status === status).length;
          if (count === 0) return null;
          return (
            <Badge key={status} variant="secondary" className={`${STATUS_COLORS[status]} font-mono`}>
              {STATUS_LABELS[status]}: {count}
            </Badge>
          );
        })}
      </div>

      {items.length === 0 ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={Briefcase}
              title="No applications tracked yet"
              description="As you mark jobs Applied from the Review Queue, they'll show up here grouped by status."
              action={{ label: "Open Review Queue", href: "/dashboard/review" }}
            />
          </CardContent>
        </Card>
      ) : (
        grouped.map(({ status, items: statusItems }) => (
          <Card key={status}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${STATUS_DOTS[status] || "bg-white/20"}`} />
                {STATUS_LABELS[status]}
                <Badge variant="outline" className="font-mono text-xs ml-1">{statusItems.length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {statusItems.map((item: any) => {
                const due = relativeDate(item.follow_up_date);
                return (
                <div key={item.id} className="flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 hover:bg-white/[0.03] transition-colors">
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{item.job?.title || "Unknown role"}</p>
                    <p className="text-xs text-muted-foreground truncate">{item.job?.company || ""}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {due && (
                      <span className={`text-xs ${
                        due.tone === "due" ? "text-amber-400 font-medium"
                        : due.tone === "soon" ? "text-amber-400/70"
                        : due.tone === "past" ? "text-red-400/80"
                        : "text-muted-foreground"
                      }`}>
                        {due.text}
                      </span>
                    )}
                    {/* Surface the most likely next-step as a one-click button so
                        the user doesn't have to open the dropdown for the common case. */}
                    {status === "approved" && (
                      <Button
                        size="xs"
                        onClick={() => changeStatus(item.id, "applied", item)}
                        title="Mark this application as Applied"
                      >
                        <Send className="h-3 w-3" />
                        Mark Applied
                      </Button>
                    )}
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button variant="ghost" size="icon-xs">
                            <ChevronDown className="h-3.5 w-3.5" />
                          </Button>
                        }
                      />
                      <DropdownMenuContent align="end">
                        {status === "approved" && (
                          <DropdownMenuItem onClick={() => changeStatus(item.id, "applied", item)}>
                            Mark as Applied
                          </DropdownMenuItem>
                        )}
                        {status === "applied" && (
                          <>
                            <DropdownMenuItem onClick={() => changeStatus(item.id, "interviewing", item)}>
                              Mark as Interviewing
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => changeStatus(item.id, "rejected", item)}>
                              Mark as Rejected
                            </DropdownMenuItem>
                          </>
                        )}
                        {status === "follow_up_due" && (
                          <>
                            <DropdownMenuItem onClick={() => changeStatus(item.id, "interviewing", item)}>
                              Mark as Interviewing
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => changeStatus(item.id, "ghosted", item)}>
                              Mark as Ghosted
                            </DropdownMenuItem>
                          </>
                        )}
                        {status === "interviewing" && (
                          <>
                            <DropdownMenuItem onClick={() => changeStatus(item.id, "offered", item)}>
                              Mark as Offered
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => changeStatus(item.id, "rejected", item)}>
                              Mark as Rejected
                            </DropdownMenuItem>
                          </>
                        )}
                        <DropdownMenuItem onClick={() => changeStatus(item.id, "archived", item)}>
                          Archive
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
                );
              })}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
