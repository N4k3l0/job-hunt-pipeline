"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Users,
  Mail,
  Shield,
  UserPlus,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api-client";

interface UserRecord {
  id: string;
  email: string;
  name: string;
  role: string;
}

export default function AdminPage() {
  const [email, setEmail] = useState("");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteResult, setInviteResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [usersLoaded, setUsersLoaded] = useState(false);

  async function loadUsers() {
    try {
      const data = await api.get<UserRecord[]>("/api/v1/auth/users");
      setUsers(data);
      setUsersLoaded(true);
    } catch (e: any) {
      if (e.message?.includes("403")) {
        setInviteResult({ ok: false, message: "Admin access required" });
      }
    }
  }

  async function handleInvite() {
    if (!email.trim()) return;
    setInviteLoading(true);
    setInviteResult(null);
    try {
      await api.post("/api/v1/auth/invite", { email: email.trim() });
      setInviteResult({ ok: true, message: `Invite sent to ${email}` });
      setEmail("");
      loadUsers();
    } catch (e: any) {
      setInviteResult({ ok: false, message: e.message || "Failed to invite" });
    } finally {
      setInviteLoading(false);
    }
  }

  // Load users on mount
  if (!usersLoaded) {
    loadUsers();
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Admin</h1>
        <p className="text-muted-foreground">
          Manage users and system settings
        </p>
      </div>

      {/* Invite User */}
      <Card style={{ background: "linear-gradient(135deg, rgba(251,191,36,0.02) 0%, transparent 60%)" }}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5 text-amber-400" />
            Invite User
          </CardTitle>
          <CardDescription>
            Send an invite email. The user will set their password and can log in.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <div className="flex-1">
              <Label htmlFor="invite-email" className="sr-only">Email</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setInviteResult(null);
                }}
                placeholder="colleague@example.com"
                onKeyDown={(e) => e.key === "Enter" && handleInvite()}
              />
            </div>
            <Button onClick={handleInvite} disabled={inviteLoading || !email.trim()}>
              {inviteLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Mail className="h-4 w-4" />
              )}
              {inviteLoading ? "Sending..." : "Send invite"}
            </Button>
          </div>
          {inviteResult && (
            <div className={`flex items-center gap-2 mt-3 text-sm ${
              inviteResult.ok ? "text-emerald-400" : "text-red-400"
            }`}>
              {inviteResult.ok ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <AlertCircle className="h-4 w-4" />
              )}
              {inviteResult.message}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Users List */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Users
          </CardTitle>
          <CardDescription>
            {users.length} registered user{users.length !== 1 ? "s" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {users.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              No users yet. Invite yourself first via the Supabase dashboard, then log in.
            </p>
          ) : (
            <div className="space-y-2">
              {users.map((user) => (
                <div
                  key={user.id}
                  className="flex items-center justify-between rounded-lg px-3 py-3 border border-white/[0.04] hover:border-white/[0.08] transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-full bg-white/[0.05] flex items-center justify-center text-sm font-medium">
                      {user.name.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-medium">{user.name}</p>
                      <p className="text-xs text-muted-foreground">{user.email}</p>
                    </div>
                  </div>
                  <Badge
                    variant={user.role === "admin" ? "default" : "secondary"}
                    className={user.role === "admin"
                      ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                      : ""
                    }
                  >
                    <Shield className="h-3 w-3 mr-1" />
                    {user.role}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
