"use client";

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
} from "lucide-react";
import { createClient } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

const navItems = [
  { title: "Jobs Inbox", href: "/dashboard/jobs", icon: Briefcase },
  { title: "Review Queue", href: "/dashboard/review", icon: ClipboardCheck },
  { title: "Applications", href: "/dashboard/applications", icon: FileText },
  { title: "Import", href: "/dashboard/import", icon: Import },
  { title: "Analytics", href: "/dashboard/analytics", icon: BarChart3 },
];

const profileItems = [
  { title: "Profile", href: "/dashboard/profile", icon: User },
  { title: "Admin", href: "/dashboard/admin", icon: Settings },
];

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <Sidebar>
      <SidebarHeader className="border-b px-6 py-5">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <Briefcase className="h-7 w-7" />
          <span className="text-xl font-bold tracking-tight">Job Hunt</span>
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
      <SidebarFooter className="border-t p-4">
        <Button
          variant="ghost"
          className="w-full justify-start text-[15px] py-3 h-auto"
          onClick={handleSignOut}
        >
          <LogOut className="mr-2.5 h-5 w-5" />
          Sign out
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}
