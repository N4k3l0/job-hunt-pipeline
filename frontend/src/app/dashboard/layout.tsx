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
    <SidebarProvider>
      <QueueWatcher />
      <RoleAutoSuggest />
      <AppSidebar />
      <main className="flex-1 overflow-auto">
        <div className="flex items-center gap-2 border-b px-4 sm:px-6 py-3">
          <SidebarTrigger />
        </div>
        <div className="p-4 sm:p-6">
          {/* OnboardingGate is a no-op once the user has a name + at
              least one resume; before that it replaces the requested
              page with a 2-step setup wizard so new invitees can't
              land on a useless empty inbox. */}
          <OnboardingGate>
            <PageTransition>{children}</PageTransition>
          </OnboardingGate>
        </div>
      </main>
    </SidebarProvider>
  );
}
