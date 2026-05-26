"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Briefcase,
  ClipboardCheck,
  FileText,
  BarChart3,
  User,
  Import,
  Settings,
  LogOut,
  MessageSquare,
} from "lucide-react";
import { createClient } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/hooks/use-api";
import { FeedbackDialog } from "@/components/feedback-dialog";
import { ThemeToggle } from "@/components/layout/theme-toggle";

const navItems = [
  { title: "Jobs Inbox", href: "/dashboard/jobs", icon: Briefcase },
  { title: "Review Queue", href: "/dashboard/review", icon: ClipboardCheck },
  { title: "Applications", href: "/dashboard/applications", icon: FileText },
  { title: "Import", href: "/dashboard/import", icon: Import },
  { title: "Analytics", href: "/dashboard/analytics", icon: BarChart3 },
];

// Profile is for everyone. Admin only appears for users with role=admin —
// the page itself is also gated server-side via AdminUser dep, but hiding
// the link prevents non-admins from seeing a 403 wall they'd never use.
const PROFILE_ITEM = { title: "Profile", href: "/dashboard/profile", icon: User };
const ADMIN_ITEM = { title: "Admin", href: "/dashboard/admin", icon: Settings };

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { setOpenMobile, isMobile } = useSidebar();
  const { data: currentUser } = useCurrentUser();
  const profileItems = currentUser?.role === "admin"
    ? [PROFILE_ITEM, ADMIN_ITEM]
    : [PROFILE_ITEM];

  // Auto-collapse the mobile sheet whenever the route changes. Belt-and-
  // braces with the per-button onClick: covers cases where the click
  // handler races the navigation, or the user lands here from a
  // programmatic redirect.
  useEffect(() => {
    if (isMobile) setOpenMobile(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <Sidebar>
      <SidebarHeader className="border-b px-6 py-5">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <span
            aria-hidden
            style={{
              width: 28,
              height: 28,
              borderRadius: 7,
              background: "var(--accent)",
              color: "var(--accent-on)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-mono, ui-monospace)",
              fontWeight: 700,
              fontSize: 14,
              letterSpacing: "-0.04em",
            }}
          >
            J
          </span>
          <span className="text-[16px] font-semibold tracking-tight">Job Hunt</span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-xs font-semibold uppercase tracking-wider px-3 mb-1">
            Pipeline
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    render={<Link href={item.href} />}
                    isActive={pathname === item.href}
                    className="text-[15px] py-3 px-3 gap-3"
                    onClick={() => isMobile && setOpenMobile(false)}
                  >
                    <item.icon className="h-5 w-5" />
                    <span className="font-medium">{item.title}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel className="text-xs font-semibold uppercase tracking-wider px-3 mb-1">
            Settings
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {profileItems.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    render={<Link href={item.href} />}
                    isActive={pathname === item.href}
                    className="text-[15px] py-3 px-3 gap-3"
                    onClick={() => isMobile && setOpenMobile(false)}
                  >
                    <item.icon className="h-5 w-5" />
                    <span className="font-medium">{item.title}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t p-4 space-y-2">
        <ThemeToggle />
        <FeedbackDialog
          trigger={
            <Button
              variant="ghost"
              className="w-full justify-start text-[14px] py-2.5 h-auto"
            >
              <MessageSquare className="mr-2.5 h-4 w-4" />
              Send feedback
            </Button>
          }
        />
        <Button
          variant="ghost"
          className="w-full justify-start text-[14px] py-2.5 h-auto"
          onClick={handleSignOut}
        >
          <LogOut className="mr-2.5 h-4 w-4" />
          Sign out
        </Button>
        <UserPill user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  );
}

/* Identity pill at the bottom of the sidebar — initials avatar + name +
   role/build line. Matches the v2 handoff (`[AO] Adaeze Okoye / Invite · v1`). */
function UserPill({ user }: { user: { name?: string | null; email?: string | null; role?: string | null } | undefined }) {
  const name = (user?.name?.trim() || user?.email || "").trim();
  if (!name) return null;
  const initials = (() => {
    const raw = (user?.name?.trim() || user?.email || "");
    if (!raw) return "·";
    if (raw.includes(" ")) {
      const parts = raw.split(/\s+/).slice(0, 2);
      return parts.map((p) => p[0]?.toUpperCase() ?? "").join("");
    }
    // Single token — first 2 letters, uppercased.
    return raw.slice(0, 2).toUpperCase();
  })();
  const sub = user?.role === "admin" ? "Admin · v1" : "Invite · v1";
  return (
    <div
      className="flex items-center gap-2.5 mt-1 pt-3 border-t"
      style={{ borderColor: "var(--line)" }}
    >
      <span
        aria-hidden
        style={{
          width: 28,
          height: 28,
          borderRadius: 6,
          background: "var(--bg-elev-2)",
          color: "var(--fg)",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-mono, ui-monospace)",
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          flexShrink: 0,
        }}
      >
        {initials}
      </span>
      <div className="min-w-0 flex-1 leading-tight">
        <div
          className="truncate text-[13px] font-medium"
          style={{ color: "var(--fg)" }}
          title={name}
        >
          {name}
        </div>
        <div
          className="text-[10.5px] mt-0.5"
          style={{ color: "var(--fg-faint)", letterSpacing: "0.04em" }}
        >
          {sub}
        </div>
      </div>
    </div>
  );
}
