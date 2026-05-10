import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { QueueWatcher } from "@/components/queue-watcher";
import { RoleAutoSuggest } from "@/components/role-auto-suggest";
import { PageTransition } from "@/components/page-transition";

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
          <PageTransition>{children}</PageTransition>
        </div>
      </main>
    </SidebarProvider>
  );
}
