"use client";

import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Loader2, TrendingUp, Briefcase, FileText, BarChart3 } from "lucide-react";
import { useAnalytics } from "@/hooks/use-api";

export default function AnalyticsPage() {
  const { data: analytics, isLoading } = useAnalytics();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const stats = [
    { label: "Jobs Discovered", value: analytics?.jobs_discovered ?? 0, icon: Briefcase },
    { label: "Shortlisted", value: analytics?.jobs_shortlisted ?? 0, icon: BarChart3 },
    { label: "Applications Sent", value: analytics?.applications_sent ?? 0, icon: FileText },
    { label: "This Week", value: analytics?.applications_this_week ?? 0, icon: TrendingUp },
    { label: "Response Rate", value: `${(analytics?.response_rate ?? 0).toFixed(0)}%`, icon: TrendingUp },
    { label: "Interview Rate", value: `${(analytics?.interview_rate ?? 0).toFixed(0)}%`, icon: TrendingUp },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground">Your job search performance</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {stats.map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{stat.label}</CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground/50" />
            </CardHeader>
            <CardContent>
              <span className="font-mono text-3xl font-bold">{stat.value}</span>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Activity Over Time</CardTitle>
          <CardDescription>Charts will populate as you use the pipeline</CardDescription>
        </CardHeader>
        <CardContent className="py-8 text-center">
          <p className="text-sm text-muted-foreground">
            Apply to more jobs to see trends here.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
