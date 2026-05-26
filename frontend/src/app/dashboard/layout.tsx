import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { QueueWatcher } from "@/components/queue-watcher";
import { RoleAutoSuggest } from "@/components/role-auto-suggest";
import { PageTransition } from "@/components/page-transition";
import { OnboardingGate } from "@/components/onboarding-gate";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // .ds-root applies the v2 design tokens (LemFi-style premium fintech
    // from the Claude Design handoff). Tokens are namespaced --ds-* so
    // shadcn primitives nested below keep working.
    <SidebarProvider>
      <div className="ds-root contents">
        <QueueWatcher />
        <RoleAutoSuggest />
        <AppSidebar />
        <main className="flex-1 overflow-auto" style={{ background: "var(--ds-bg)" }}>
          <div className="flex items-center gap-2 border-b px-4 sm:px-6 py-3" style={{ borderColor: "var(--ds-line)" }}>
            <SidebarTrigger />
          </div>
          <div className="p-4 sm:p-6">
            {/* OnboardingGate is a no-op once the user has a name +
                resume + countries; before that it replaces the requested
                page with the 3-step setup wizard. */}
            <OnboardingGate>
              <PageTransition>{children}</PageTransition>
            </OnboardingGate>
          </div>
        </main>
      </div>
    </SidebarProvider>
  );
}
