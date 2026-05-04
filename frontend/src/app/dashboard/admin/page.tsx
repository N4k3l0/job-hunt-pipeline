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
  const [inviteResult, setInviteResult] = useState<{
    ok: boolean;
    message: string;
    magicLink?: string | null;
  } | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);
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

  // Tracks the email tied to the most recent failed-because-exists invite,
  // so the inline "Resend magic link" button knows what to act on.
  const [conflictedEmail, setConflictedEmail] = useState<string | null>(null);

  async function handleInvite() {
    if (!email.trim()) return;
    setInviteLoading(true);
    setInviteResult(null);
    setLinkCopied(false);
    setConflictedEmail(null);
    const target = email.trim();
    try {
      const data = await api.post<{
        status: string;
        email: string;
        magic_link?: string | null;
      }>("/api/v1/auth/invite", { email: target });
      setInviteResult({
        ok: true,
        message: `Invite email sent to ${data.email}. They'll get a one-tap link.`,
        magicLink: data.magic_link,
      });
      setEmail("");
      loadUsers();
    } catch (e: any) {
      // 409 → the user already exists. Offer to mint a fresh magic link
      // instead of pretending the invite worked.
      const message = e?.message || "Failed to invite";
      const looksLikeConflict = /409|already has an account|already been registered/i.test(message);
      if (looksLikeConflict) {
        setConflictedEmail(target);
        setInviteResult({
          ok: false,
          message: `${target} already has an account. Send them a fresh magic link instead?`,
        });
      } else {
        setInviteResult({ ok: false, message });
      }
    } finally {
      setInviteLoading(false);
    }
  }

  async function handleResendMagicLink(targetEmail: string) {
    setInviteLoading(true);
    setLinkCopied(false);
    try {
      const data = await api.post<{
        email: string;
        magic_link?: string | null;
      }>("/api/v1/auth/resend-magic-link", { email: targetEmail });
      setConflictedEmail(null);
      setInviteResult({
        ok: true,
        message: `Fresh magic link minted for ${data.email}. Copy and send it directly.`,
        magicLink: data.magic_link,
      });
    } catch (e: any) {
      setInviteResult({
        ok: false,
        message: e?.message || "Failed to mint magic link",
      });
    } finally {
      setInviteLoading(false);
    }
  }

  async function copyMagicLink() {
    if (!inviteResult?.magicLink) return;
    try {
      await navigator.clipboard.writeText(inviteResult.magicLink);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch { /* clipboard blocked */ }
  }

  // Load users on mount
  if (!usersLoaded) {
    loadUsers();
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Admin</h1>
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
            Sends a magic-link email. One click → straight to the dashboard, no password.
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
            <div className="mt-3 space-y-3">
              <div className={`flex items-start gap-2 text-sm ${
                inviteResult.ok ? "text-emerald-400" : "text-red-400"
              }`}>
                {inviteResult.ok ? (
                  <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
                ) : (
                  <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                )}
                <span>{inviteResult.message}</span>
              </div>
              {conflictedEmail && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleResendMagicLink(conflictedEmail)}
                  disabled={inviteLoading}
                  className="border-amber-500/30 text-amber-400 hover:bg-amber-500/5"
                >
                  {inviteLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}
                  Send fresh magic link to {conflictedEmail}
                </Button>
              )}
              {inviteResult.ok && inviteResult.magicLink && (
                <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] p-3 space-y-2">
                  <p className="text-xs text-amber-200/70 font-medium">
                    Magic link (single-use, expires in ~1 hour)
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 truncate rounded bg-black/40 px-2 py-1.5 text-[11px] text-amber-200/90 font-mono">
                      {inviteResult.magicLink}
                    </code>
                    <Button
                      size="xs"
                      variant="default"
                      onClick={copyMagicLink}
                      className="shrink-0"
                    >
                      {linkCopied ? "Copied" : "Copy"}
                    </Button>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    Paste it into WhatsApp, SMS, or email. Tapping it on any device
                    signs them straight in — no password.
                  </p>
                </div>
              )}
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
