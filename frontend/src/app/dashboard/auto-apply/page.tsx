"use client";

import Link from "next/link";
import { ChevronRight, Loader2, Send } from "lucide-react";
import { useAutoApplications } from "@/hooks/use-api";
import { EmptyState } from "@/components/ui/empty-state";
import { AutoApplyStatusPill } from "@/components/auto-apply-status";
import type { AutoApplication, AutoApplicationStatus } from "@/lib/types";

const SECTIONS: { title: string; statuses: AutoApplicationStatus[]; hint: string }[] = [
  { title: "Needs you", statuses: ["needs_you", "preparing"], hint: "Answer or confirm the questions the app couldn't." },
  { title: "Approved", statuses: ["queued", "submitting"], hint: "Every answer is ready." },
  { title: "Sent", statuses: ["submitted"], hint: "" },
  { title: "Couldn't apply", statuses: ["failed", "unsupported"], hint: "Closed postings and forms the app can't fill in." },
  { title: "Stopped", statuses: ["cancelled"], hint: "" },
];

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function Row({ application }: { application: AutoApplication }) {
  const detail =
    application.status === "needs_you"
      ? `${application.open_count} ${application.open_count === 1 ? "question needs" : "questions need"} you`
      : application.error ?? "";
  return (
    <Link
      href={`/dashboard/auto-apply/${application.id}`}
      className="ds-row"
      style={{ gridTemplateColumns: "1fr auto auto", alignItems: "center" }}
    >
      <div className="min-w-0">
        <div className="ds-muted truncate" style={{ fontSize: 13 }}>{application.job?.company}</div>
        <div className="truncate" style={{ fontSize: 15, fontWeight: 500 }}>{application.job?.title}</div>
        {detail && <div className="ds-dim truncate" style={{ fontSize: 12, marginTop: 2 }}>{detail}</div>}
      </div>
      <div className="flex items-center" style={{ gap: 10 }}>
        <span className="ds-mono ds-dim hidden sm:inline" style={{ fontSize: 12 }}>{timeAgo(application.updated_at)}</span>
        <AutoApplyStatusPill status={application.status} />
      </div>
      <ChevronRight className="h-4 w-4 ds-dim" />
    </Link>
  );
}

export default function AutoApplyPage() {
  const { data: applications, isLoading } = useAutoApplications();

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 900, margin: "0 auto" }}>
        <div>
          <h1 className="ds-h1">Apply for me</h1>
          <p className="ds-muted" style={{ marginTop: 6, maxWidth: 620 }}>
            The app reads each job&apos;s application form and fills in what your profile answers. You check the
            rest, then the <Link href="/dashboard/extension" className="ds-accent-fg">Chrome extension</Link> fills
            in the company&apos;s form for you to send.
          </p>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin ds-dim" />
          </div>
        ) : !applications?.length ? (
          <EmptyState
            icon={Send}
            title="No applications yet"
            description="Open a job from Greenhouse, Lever or Ashby and press Apply for me."
            action={{ label: "Go to inbox", href: "/dashboard/jobs" }}
          />
        ) : (
          SECTIONS.map((section) => {
            const rows = applications.filter((a) => section.statuses.includes(a.status));
            if (!rows.length) return null;
            return (
              <section key={section.title} className="space-y-2">
                <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
                  <h2 className="ds-h3">
                    {section.title} <span className="ds-mono ds-dim" style={{ fontSize: 13 }}>{rows.length}</span>
                  </h2>
                  {section.hint && <span className="ds-dim" style={{ fontSize: 12 }}>{section.hint}</span>}
                </div>
                <div className="ds-card" style={{ overflow: "hidden" }}>
                  {rows.map((application) => (
                    <Row key={application.id} application={application} />
                  ))}
                </div>
              </section>
            );
          })
        )}
      </div>
    </div>
  );
}
