"use client";

import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronDown, Bell, Loader2 } from "lucide-react";
import { useApplicationPipeline, useUpdateStatus, useReminders } from "@/hooks/use-api";

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

  const items = tracking ?? [];
  const reminderCount = reminders?.length ?? 0;

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
          <h1 className="text-3xl font-bold tracking-tight">Applications</h1>
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
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No applications tracked yet.</p>
            <p className="text-sm text-muted-foreground/60 mt-1">
              Approve tailored materials from the Review Queue to start tracking.
            </p>
          </CardContent>
        </Card>
      ) : (
        grouped.map(({ status, items: statusItems }) => (
          <Card key={status}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${STATUS_DOTS[status] || "bg-white/20"}`} />
                {STATUS_LABELS[status]}
                <Badge variant="outline" className="font-mono text-[10px] ml-1">{statusItems.length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {statusItems.map((item: any) => (
                <div key={item.id} className="flex items-center justify-between rounded-lg px-3 py-2.5 hover:bg-white/[0.03] transition-colors">
                  <div>
                    <p className="text-sm font-medium">{item.job?.title || "Unknown role"}</p>
                    <p className="text-xs text-muted-foreground">{item.job?.company || ""}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {item.follow_up_date && (
                      <span className={`text-xs font-mono ${
                        new Date(item.follow_up_date) <= new Date() ? "text-amber-400" : "text-muted-foreground"
                      }`}>
                        {item.follow_up_date}
                      </span>
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
                          <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "applied" })}>
                            Mark as Applied
                          </DropdownMenuItem>
                        )}
                        {status === "applied" && (
                          <>
                            <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "interviewing" })}>
                              Mark as Interviewing
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "rejected" })}>
                              Mark as Rejected
                            </DropdownMenuItem>
                          </>
                        )}
                        {status === "follow_up_due" && (
                          <>
                            <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "interviewing" })}>
                              Mark as Interviewing
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "ghosted" })}>
                              Mark as Ghosted
                            </DropdownMenuItem>
                          </>
                        )}
                        {status === "interviewing" && (
                          <>
                            <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "offered" })}>
                              Mark as Offered
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "rejected" })}>
                              Mark as Rejected
                            </DropdownMenuItem>
                          </>
                        )}
                        <DropdownMenuItem onClick={() => updateStatus.mutate({ id: item.id, status: "archived" })}>
                          Archive
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
