"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
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
  LayoutDashboard,
  Inbox,
  ClipboardList,
  Send,
  BarChart3,
  User,
  Settings,
  LogOut,
  MessageSquare,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { createClient } from "@/lib/supabase";
import {
  useCurrentUser,
  useAnalytics,
  useReviewQueue,
} from "@/hooks/use-api";
import { FeedbackDialog } from "@/components/feedback-dialog";
import { ThemeToggle } from "@/components/layout/theme-toggle";

type Item = {
  title: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  countKey?: "review" | "applied";
};

const PIPELINE_ITEMS: Item[] = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Inbox", href: "/dashboard/jobs", icon: Inbox },
  { title: "Review Queue", href: "/dashboard/review", icon: ClipboardList, countKey: "review" },
  { title: "Applications", href: "/dashboard/applications", icon: Send, countKey: "applied" },
  { title: "Analytics", href: "/dashboard/analytics", icon: BarChart3 },
];

const ACCOUNT_ITEMS: Item[] = [
  { title: "Profile", href: "/dashboard/profile", icon: User },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { setOpenMobile, isMobile } = useSidebar();
  const { data: currentUser } = useCurrentUser();
  const { data: analytics } = useAnalytics();
  const { data: reviewQueue } = useReviewQueue();

  const counts = {
    review: (reviewQueue ?? []).filter((r: { approval_status?: string }) => r.approval_status === "ready").length,
    applied: analytics?.applications_sent ?? 0,
  };

  // Auto-collapse the mobile sheet whenever the route changes.
  useEffect(() => {
    if (isMobile) setOpenMobile(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const renderItem = (item: Item) => {
    const isActive = pathname === item.href;
    const count = item.countKey ? counts[item.countKey] : undefined;
    return (
      <SidebarMenuItem key={item.href}>
        <SidebarMenuButton
          render={<Link href={item.href} />}
          isActive={isActive}
          // Override the default shadcn active treatment (which uses
          // primary/accent text + glow) with a calm "filled card" — bg-elev-1
          // + normal fg text. Matches the Claude design.
          className={[
            "h-10 gap-3 px-3 text-[14px] font-medium",
            "data-[active=true]:bg-[var(--bg-elev-1)]",
            "data-[active=true]:text-[var(--fg)]",
            "hover:bg-[var(--bg-elev-1)] hover:text-[var(--fg)]",
            "text-[var(--fg-muted)]",
          ].join(" ")}
          onClick={() => isMobile && setOpenMobile(false)}
        >
          <item.icon size={16} className="opacity-90" />
          <span className="flex-1 truncate">{item.title}</span>
          {count !== undefined && count > 0 && (
            <span
              className="ds-mono"
              style={{
                fontSize: 11,
                color: isActive ? "var(--accent)" : "var(--fg-dim)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {count}
            </span>
          )}
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  return (
    <Sidebar>
      <SidebarHeader className="px-6 py-5">
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
          <SidebarGroupLabel
            className="text-[11px] font-semibold uppercase tracking-[0.09em] px-3 mb-1"
            style={{ color: "var(--fg-faint)" }}
          >
            Pipeline
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{PIPELINE_ITEMS.map(renderItem)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel
            className="text-[11px] font-semibold uppercase tracking-[0.09em] px-3 mb-1"
            style={{ color: "var(--fg-faint)" }}
          >
            Account
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{ACCOUNT_ITEMS.map(renderItem)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="p-4 space-y-3">
        <ThemeToggle />
        <UserPill user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  );
}

/* Identity strip + settings dropdown — initials avatar, name, role/build
   line, and a ⚙ that opens Send feedback / (Admin) / Sign out. Matches
   the Claude design's compact footer. */
function UserPill({
  user,
}: {
  user:
    | { name?: string | null; email?: string | null; role?: string | null }
    | undefined;
}) {
  const router = useRouter();
  const name = (user?.name?.trim() || user?.email || "").trim();
  if (!name) return null;
  const initials = (() => {
    const raw = user?.name?.trim() || user?.email || "";
    if (!raw) return "·";
    if (raw.includes(" ")) {
      const parts = raw.split(/\s+/).slice(0, 2);
      return parts.map((p) => p[0]?.toUpperCase() ?? "").join("");
    }
    return raw.slice(0, 2).toUpperCase();
  })();
  const sub = user?.role === "admin" ? "Admin · v1" : "Invite · v1";

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <div
      className="flex items-center gap-2.5 pt-3"
      style={{ borderTop: "1px solid var(--line)" }}
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
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="Settings"
            className="inline-flex items-center justify-center"
            style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              color: "var(--fg-muted)",
              background: "transparent",
              border: 0,
              cursor: "pointer",
              flexShrink: 0,
              transition: "color 120ms ease, background 120ms ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--bg-hover)";
              e.currentTarget.style.color = "var(--fg)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "var(--fg-muted)";
            }}
          >
            <Settings size={14} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="end" className="w-56">
          <FeedbackDialog
            trigger={
              <DropdownMenuItem onSelect={(e) => e.preventDefault()}>
                <MessageSquare className="mr-2 h-4 w-4" />
                Send feedback
              </DropdownMenuItem>
            }
          />
          {user?.role === "admin" && (
            <DropdownMenuItem asChild>
              <Link href="/dashboard/admin">
                <Settings className="mr-2 h-4 w-4" />
                Admin
              </Link>
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={handleSignOut}>
            <LogOut className="mr-2 h-4 w-4" />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
