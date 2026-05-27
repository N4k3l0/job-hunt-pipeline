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
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Users,
  Mail,
  Shield,
  UserPlus,
  Loader2,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Trash2,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api-client";
import {
  useRunDiscovery,
  useStaleJobsPreview,
  useStaleJobsCleanup,
  useStaleJobsVerifyBatch,
  useStaleJobsVerifyDebug,
  useCleanupBySource,
  useEmbeddingsBackfill,
} from "@/hooks/use-api";

interface UserRecord {
  id: string;
  email: string;
  name: string;
  role: string;
}

export default function AdminPage() {
  const runDiscovery = useRunDiscovery();
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
                  <p className="text-sm text-amber-200 font-medium">
                    Magic link (single-use, expires in ~1 hour)
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 truncate rounded bg-black/40 px-2 py-1.5 text-xs text-amber-200 font-mono">
                      {inviteResult.magicLink}
                    </code>
                    <Button
                      size="sm"
                      variant="default"
                      onClick={copyMagicLink}
                      className="shrink-0"
                    >
                      {linkCopied ? "Copied" : "Copy"}
                    </Button>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Paste it into WhatsApp, SMS, or email. Tapping it on any device
                    signs them straight in — no password.
                  </p>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* All operational tooling consolidated into one tabbed panel —
          previously 4 cards stacked on the page. Same components, just
          shown one at a time so the page reads as
          [Invite User · Maintenance · Users] instead of a wall of cards. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-400" />
            Maintenance &amp; diagnostics
          </CardTitle>
          <CardDescription>
            Run discovery on demand, top up embeddings, diagnose the
            country filter, or clean out stale jobs. Each tab is the
            same tooling you had before — just collapsed so the page
            doesn&apos;t scroll forever.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="discovery">
            <TabsList className="mb-4">
              <TabsTrigger value="discovery">
                <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                Discovery
              </TabsTrigger>
              <TabsTrigger value="embeddings">
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                Embeddings
              </TabsTrigger>
              <TabsTrigger value="diagnostics">
                <AlertCircle className="h-3.5 w-3.5 mr-1.5" />
                Diagnostics
              </TabsTrigger>
              <TabsTrigger value="cleanup">
                <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                Cleanup
              </TabsTrigger>
            </TabsList>

            <TabsContent value="discovery">
              <RunDiscoveryPanel />
            </TabsContent>
            <TabsContent value="embeddings">
              <EmbeddingsBackfillCard />
            </TabsContent>
            <TabsContent value="diagnostics">
              <CountryFilterDebugCard />
            </TabsContent>
            <TabsContent value="cleanup">
              <StaleJobsCard />
            </TabsContent>
          </Tabs>
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

      <SourceHealthCard />
      <TranslateTitlesCard />
    </div>
  );
}


/* ============================================================
   TranslateTitlesCard — one-click backfill of English translations
   for existing non-English job titles. Burns ~$0.00001 per title
   via Anthropic Haiku. Re-run until "more to do" goes false.
   ============================================================ */
type TranslateResult = {
  inspected: number;
  translated: number;
  skipped_already_english: number;
  failed: number;
  more_to_do: boolean;
};

function TranslateTitlesCard() {
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<TranslateResult[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const cumulative = history.reduce(
    (acc, r) => ({
      translated: acc.translated + r.translated,
      skipped: acc.skipped + r.skipped_already_english,
      failed: acc.failed + r.failed,
    }),
    { translated: 0, skipped: 0, failed: 0 },
  );

  const run = async () => {
    setRunning(true);
    setErr(null);
    try {
      const result = await api.post<TranslateResult>(
        "/api/v1/auth/admin/backfill-title-translations?limit=30",
      );
      setHistory((h) => [...h, result]);
    } catch (e: any) {
      setErr(e?.message || "Backfill failed");
    } finally {
      setRunning(false);
    }
  };

  const lastResult = history[history.length - 1];
  const done = lastResult && !lastResult.more_to_do;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" />
          Translate non-English titles
        </CardTitle>
        <CardDescription>
          Translates titles for existing German / Dutch / etc. jobs to
          English using Anthropic Haiku (~$0.00001 per title). New jobs
          are translated automatically at ingest — this card is just for
          the historical catalogue. Runs in batches of 30 to stay under
          the 60-second Vercel timeout. Click again until "all done."
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Button onClick={run} disabled={running}>
            {running ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Translating 30…
              </>
            ) : done ? (
              <>
                <CheckCircle2 className="h-4 w-4" />
                All done
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                {history.length === 0 ? "Run translation backfill" : "Run next 30"}
              </>
            )}
          </Button>
          {history.length > 0 && (
            <span className="text-xs text-muted-foreground">
              Session total: <span className="font-mono">{cumulative.translated}</span> translated ·{" "}
              <span className="font-mono">{cumulative.skipped}</span> already English ·{" "}
              <span className="font-mono">{cumulative.failed}</span> failed
            </span>
          )}
        </div>

        {err && (
          <p className="text-sm" style={{ color: "#ef4444" }}>
            {err}
          </p>
        )}

        {lastResult && (
          <div
            style={{
              fontSize: 12,
              color: "var(--ds-fg-muted)",
              padding: "8px 10px",
              background: "var(--ds-bg-elev-1)",
              border: "1px solid var(--ds-line)",
              borderRadius: 6,
            }}
          >
            Last batch — inspected <span className="font-mono">{lastResult.inspected}</span>,
            translated <span className="font-mono" style={{ color: "var(--ds-accent)" }}>{lastResult.translated}</span>,
            already-English <span className="font-mono">{lastResult.skipped_already_english}</span>,
            failed <span className="font-mono">{lastResult.failed}</span>.
            {lastResult.more_to_do
              ? " There are more to translate — click \"Run next 30\"."
              : " Catalogue is fully translated."}
          </div>
        )}
      </CardContent>
    </Card>
  );
}


/* ============================================================
   SourceHealthCard — one-click diagnostic that hits the backend
   probe endpoint and renders per-source status. Used when a
   scraper appears to be silently producing zero jobs and we
   want to know WHY without checking Vercel logs.
   ============================================================ */
type SourceProbe = {
  source: string;
  status: "ok" | "empty" | "error" | "timeout" | "skipped";
  count: number;
  elapsed_s: number;
  sample_title?: string | null;
  reason?: string;
  error?: string;
};

function SourceHealthCard() {
  const [probing, setProbing] = useState(false);
  const [results, setResults] = useState<SourceProbe[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setProbing(true);
    setErr(null);
    try {
      const data = await api.get<{ sources: SourceProbe[] }>(
        "/api/v1/auth/admin/debug/source-health",
      );
      // Sort so the broken ones (anything not 'ok') float to the top.
      const sorted = [...(data.sources || [])].sort((a, b) => {
        const order = { error: 0, timeout: 1, empty: 2, skipped: 3, ok: 4 } as Record<string, number>;
        return (order[a.status] ?? 9) - (order[b.status] ?? 9);
      });
      setResults(sorted);
    } catch (e: any) {
      setErr(e?.message || "Probe failed");
    } finally {
      setProbing(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" />
          Source health
        </CardTitle>
        <CardDescription>
          Live-fires every discovery scraper with a small probe (max 2 detail
          fetches each) and reports what came back. Use when a source has
          stopped producing jobs to tell apart "scraper returns zero" vs
          "scraper crashes" vs "env var missing."
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Button onClick={run} disabled={probing}>
            {probing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Probing all sources…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                {results ? "Re-run probe" : "Run source health check"}
              </>
            )}
          </Button>
          {results && (
            <span className="text-xs text-muted-foreground">
              Last run hit {results.length} sources.
              {" "}Broken first.
            </span>
          )}
        </div>

        {err && (
          <p className="text-sm" style={{ color: "#ef4444" }}>
            {err}
          </p>
        )}

        {results && results.length > 0 && (
          <div
            style={{
              border: "1px solid var(--ds-line)",
              borderRadius: 8,
              overflow: "hidden",
            }}
          >
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--ds-bg-elev-1)" }}>
                  <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500, color: "var(--ds-fg-muted)", borderBottom: "1px solid var(--ds-line)" }}>Source</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500, color: "var(--ds-fg-muted)", borderBottom: "1px solid var(--ds-line)" }}>Status</th>
                  <th style={{ textAlign: "right", padding: "8px 12px", fontWeight: 500, color: "var(--ds-fg-muted)", borderBottom: "1px solid var(--ds-line)" }}>Count</th>
                  <th style={{ textAlign: "right", padding: "8px 12px", fontWeight: 500, color: "var(--ds-fg-muted)", borderBottom: "1px solid var(--ds-line)" }}>Elapsed</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500, color: "var(--ds-fg-muted)", borderBottom: "1px solid var(--ds-line)" }}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <SourceHealthRow key={r.source} probe={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SourceHealthRow({ probe }: { probe: SourceProbe }) {
  const dotColor =
    probe.status === "ok" ? "var(--ds-accent)"
    : probe.status === "empty" ? "var(--ds-fg-dim)"
    : probe.status === "skipped" ? "var(--ds-fg-faint)"
    : "#ef4444";
  const detail =
    probe.error ? probe.error
    : probe.reason ? probe.reason
    : probe.sample_title ? `"${probe.sample_title}"`
    : probe.status === "empty" ? "No jobs returned"
    : "—";
  return (
    <tr style={{ borderTop: "1px solid var(--ds-line-faint)" }}>
      <td style={{ padding: "10px 12px", fontWeight: 500 }}>
        {probe.source}
      </td>
      <td style={{ padding: "10px 12px" }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: dotColor,
              flexShrink: 0,
            }}
          />
          <span
            className="font-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: dotColor,
            }}
          >
            {probe.status}
          </span>
        </span>
      </td>
      <td
        className="font-mono tabular-nums"
        style={{
          padding: "10px 12px",
          textAlign: "right",
          color: probe.count > 0 ? "var(--ds-fg)" : "var(--ds-fg-dim)",
        }}
      >
        {probe.count}
      </td>
      <td
        className="font-mono tabular-nums"
        style={{
          padding: "10px 12px",
          textAlign: "right",
          color: "var(--ds-fg-muted)",
        }}
      >
        {probe.elapsed_s.toFixed(1)}s
      </td>
      <td
        style={{
          padding: "10px 12px",
          color: "var(--ds-fg-muted)",
          fontSize: 12,
          maxWidth: 340,
          wordBreak: "break-word",
        }}
      >
        {detail}
      </td>
    </tr>
  );
}


/**
 * Bulk-archive jobs older than N days that nobody applied to. Marks them
 * status='expired' so they drop out of every inbox while staying in the
 * DB (so application_tracking FKs don't break and audit history survives).
 *
 * Re-runnable. Default cutoff = 30 days; user can change with the input.
 */
function RunDiscoveryPanel() {
  const runDiscovery = useRunDiscovery();
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Pulls fresh jobs from every active source and re-scores everyone&apos;s
        inbox. Same code path as the 06:00 UTC cron, but on-demand.
        Takes ~30–45 s.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => runDiscovery.mutate()}
          disabled={runDiscovery.isPending}
        >
          {runDiscovery.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Running…
            </>
          ) : (
            <>
              <RefreshCw className="h-4 w-4" />
              Run now
            </>
          )}
        </Button>
        {runDiscovery.isSuccess && runDiscovery.data && (
          <span className="flex items-center gap-1.5 text-sm text-emerald-400">
            <CheckCircle2 className="h-4 w-4" /> Done
          </span>
        )}
        {runDiscovery.isError && (
          <span className="flex items-center gap-1.5 text-sm text-destructive">
            <AlertCircle className="h-4 w-4" /> Failed
          </span>
        )}
      </div>
      {runDiscovery.isSuccess && runDiscovery.data && (
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] p-3 text-xs space-y-2">
          <div>
            <p className="font-medium text-muted-foreground mb-1">Sources</p>
            <ul className="space-y-0.5 font-mono">
              {Object.entries(runDiscovery.data.results).map(([name, status]) => (
                <li key={name} className="flex justify-between gap-3">
                  <span>{name}</span>
                  <span className={status.startsWith("ok") ? "text-emerald-400" : "text-amber-400"}>
                    {status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="font-medium text-muted-foreground mb-1">Scoring</p>
            <ul className="space-y-0.5 font-mono">
              {Object.entries(runDiscovery.data.scoring).map(([uid, status]) => (
                <li key={uid} className="flex justify-between gap-3">
                  <span className="truncate">{uid.slice(0, 8)}…</span>
                  <span className={status.startsWith("ok") ? "text-emerald-400" : "text-amber-400"}>
                    {status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}


function StaleJobsCard() {
  const [days, setDays] = useState(30);
  const preview = useStaleJobsPreview(days);
  const cleanup = useStaleJobsCleanup();
  const verify = useStaleJobsVerifyBatch();
  const debug = useStaleJobsVerifyDebug();
  const cleanupSource = useCleanupBySource();

  // Verify mode runs in batches of 100 jobs each so we stay under
  // Vercel's 60s function timeout. Auto-chain until has_more=false so
  // the user clicks once and the whole catalogue gets probed.
  const [verifyTotals, setVerifyTotals] = useState<{
    checked: number; expired: number; alive: number; ambiguous: number; skipped: number;
  } | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyDone, setVerifyDone] = useState(false);

  const runVerify = async () => {
    setVerifying(true);
    setVerifyDone(false);
    setVerifyTotals({ checked: 0, expired: 0, alive: 0, ambiguous: 0, skipped: 0 });
    let safetyCap = 50; // cap at 50 batches × 100 = 5k jobs/run
    while (safetyCap-- > 0) {
      try {
        const batch = await verify.mutateAsync({ limit: 100 });
        setVerifyTotals((prev) => ({
          checked: (prev?.checked ?? 0) + batch.checked,
          expired: (prev?.expired ?? 0) + batch.expired,
          alive: (prev?.alive ?? 0) + batch.alive,
          ambiguous: (prev?.ambiguous ?? 0) + batch.ambiguous,
          skipped: (prev?.skipped ?? 0) + (batch.skipped ?? 0),
        }));
        if (!batch.has_more || batch.checked === 0) break;
      } catch {
        break;
      }
    }
    setVerifying(false);
    setVerifyDone(true);
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Two modes: <span className="text-foreground">Verify URLs</span>{" "}
        actually probes each posting and only marks confirmed-dead ones
        (404 / 410). <span className="text-foreground">Quick clean</span>{" "}
        uses a time-based cutoff — faster but less precise. Either way,
        jobs anyone has approved or applied to are never touched.
      </p>

        {/* ── Verify URLs ────────────────────────────── */}
        <div className="space-y-3 rounded-lg border border-emerald-500/15 bg-emerald-500/[0.02] p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <p className="text-sm font-semibold flex items-center gap-2">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Verify URLs (recommended)
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 max-w-md">
                Probes each unapplied posting&apos;s apply URL. Only marks expired on a real 404 or 410.
                Runs in batches of 100; auto-continues to the end (~30s per batch on Vercel).
              </p>
            </div>
            <Button onClick={runVerify} disabled={verifying} variant="outline">
              {verifying ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Verifying…
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4" />
                  {verifyDone ? "Run again" : "Verify URLs"}
                </>
              )}
            </Button>
          </div>
          {verifyTotals && (verifying || verifyDone) && (
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs font-mono">
              <Stat label="Checked" value={verifyTotals.checked} tone="default" />
              <Stat label="Expired" value={verifyTotals.expired} tone="warn" />
              <Stat label="Alive" value={verifyTotals.alive} tone="ok" />
              <Stat label="Ambiguous" value={verifyTotals.ambiguous} tone="muted" />
              <Stat label="Skipped" value={verifyTotals.skipped} tone="muted" />
            </div>
          )}
          {verifyTotals && verifyDone && (
            <p className="text-xs text-muted-foreground">
              {verifyTotals.expired === 0
                ? "Every probed URL came back alive or ambiguous. No deaths."
                : `Marked ${verifyTotals.expired} confirmed-dead jobs as expired.`}
            </p>
          )}

          {/* Diagnostic — explain why so many came back ambiguous. Probes
              a small sample, groups outcomes by host, surfaces the actual
              status code or error class so the admin can see if it's
              anti-bot blocking, timeouts, or genuine network failures. */}
          {verifyTotals && verifyTotals.ambiguous > 0 && (
            <div className="pt-2 border-t border-white/[0.04]">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <p className="text-xs text-muted-foreground">
                  {verifyTotals.ambiguous} ambiguous results — most are likely anti-bot blocking, not real deaths. Run diagnostic to see what&apos;s happening.
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => debug.mutate({ limit: 50 })}
                  disabled={debug.isPending}
                >
                  {debug.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Diagnose ambiguous
                </Button>
              </div>
              {debug.data && (
                <div className="mt-3 rounded-md border border-white/[0.06] bg-white/[0.015] p-3 space-y-3 text-xs">
                  <div>
                    <p className="font-mono text-muted-foreground mb-1.5">Outcomes ({debug.data.checked} probed)</p>
                    <div className="flex flex-wrap gap-1.5 font-mono">
                      {Object.entries(debug.data.by_outcome)
                        .sort((a, b) => b[1] - a[1])
                        .map(([outcome, count]) => (
                          <Badge
                            key={outcome}
                            variant="outline"
                            className="text-[11px]"
                          >
                            <span className={
                              outcome === "404" || outcome === "410"
                                ? "text-red-400"
                                : outcome.startsWith("2") || outcome.startsWith("3")
                                  ? "text-emerald-400"
                                  : "text-amber-400"
                            }>
                              {outcome}
                            </span>
                            <span className="ml-1.5 text-muted-foreground">{count}</span>
                          </Badge>
                        ))}
                    </div>
                  </div>
                  <div>
                    <p className="font-mono text-muted-foreground mb-1.5">By host</p>
                    <ul className="space-y-1 font-mono">
                      {debug.data.by_host.slice(0, 12).map((row) => (
                        <li key={row.host} className="flex items-baseline gap-2">
                          <span className="truncate flex-1">{row.host}</span>
                          <span className="text-muted-foreground">{row.total}</span>
                          <span className="text-muted-foreground/60">
                            {Object.entries(row.by_outcome).map(([o, c]) => `${o}×${c}`).join(" ")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Anti-bot source cleanup ──────────────────────────── */}
        <div className="space-y-3 rounded-lg border border-amber-500/15 bg-amber-500/[0.02] p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <p className="text-sm font-semibold flex items-center gap-2">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
                Clean Adzuna jobs older than 14 days
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 max-w-md">
                Adzuna&apos;s API only serves recent listings (postings rotate within ~2–3 weeks)
                AND their redirect URLs anti-bot our verifier with HTTP 429. We can&apos;t verify them,
                so we age-cleanup with a tighter 14-day cutoff just for this source.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => cleanupSource.mutate({ source: "adzuna", days: 14 })}
              disabled={cleanupSource.isPending}
            >
              {cleanupSource.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              {cleanupSource.isPending ? "Cleaning…" : "Expire Adzuna >14d"}
            </Button>
          </div>
          {cleanupSource.isSuccess && cleanupSource.data && (
            <p className="text-xs text-emerald-400">
              Expired {cleanupSource.data.expired} {cleanupSource.data.source} jobs older than {cleanupSource.data.days} days.
            </p>
          )}
          {cleanupSource.isError && (
            <p className="text-xs text-destructive">{cleanupSource.error?.message}</p>
          )}
        </div>

        {/* ── Time-based cleanup (legacy / quick) ───────────────── */}
        <div className="space-y-3 rounded-lg border border-white/[0.06] p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <p className="text-sm font-semibold flex items-center gap-2">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
                Quick clean by age
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 max-w-md">
                Heuristic — flips anything older than the cutoff to expired.
                Fast but can mark still-open postings as dead. Use for catch-up
                sweeps; prefer Verify URLs for accuracy.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Label className="text-sm">Older than</Label>
            <Input
              type="number"
              value={days}
              min={7}
              max={365}
              onChange={(e) => setDays(Math.max(7, parseInt(e.target.value) || 30))}
              className="w-24"
            />
            <span className="text-sm text-muted-foreground">days</span>
            {preview.data && (
              <Badge variant="outline" className="font-mono text-xs">
                {preview.data.would_expire} of {preview.data.total_unapplied} would expire
              </Badge>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => cleanup.mutate({ days })}
              disabled={cleanup.isPending || !preview.data || preview.data.would_expire === 0}
            >
              {cleanup.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {cleanup.isPending ? "Cleaning…" : `Expire ${preview.data?.would_expire ?? 0} jobs`}
            </Button>
            {cleanup.isSuccess && cleanup.data && (
              <span className="flex items-center gap-1.5 text-sm text-emerald-400">
                <CheckCircle2 className="h-4 w-4" /> Expired {cleanup.data.expired} jobs
              </span>
            )}
            {cleanup.isError && (
              <span className="flex items-center gap-1.5 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" /> {cleanup.error?.message || "Failed"}
              </span>
            )}
          </div>
        </div>

    </div>
  );
}

/**
 * Bulk-embed historical jobs that don't yet have a semantic vector.
 * Used as a one-shot after the embeddings migration runs against prod —
 * new jobs ingested after that point get embedded inline during
 * discovery, so this button only matters during the rollout window.
 *
 * Auto-chains batches of 200 until has_more=false, mirroring the
 * verify-URLs flow elsewhere on this page.
 */
function EmbeddingsBackfillCard() {
  const backfill = useEmbeddingsBackfill();
  const [totals, setTotals] = useState<{
    embedded: number; remaining: number;
  } | null>(null);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);

  const [runError, setRunError] = useState<string | null>(null);

  const runBackfill = async () => {
    setRunning(true);
    setDone(false);
    setRunError(null);
    setTotals({ embedded: 0, remaining: 0 });
    // 200 batches × 10 = 2 k jobs/run — covers the catalogue with
    // headroom. Was 50/batch but kept timing out the Vercel function
    // (60s Hobby ceiling) on cold start + Supabase pooler latency +
    // Voyage round-trip. 10 keeps each call under ~15s even cold.
    let safetyCap = 200;
    while (safetyCap-- > 0) {
      try {
        const batch = await backfill.mutateAsync({ limit: 10 });
        setTotals((prev) => ({
          embedded: (prev?.embedded ?? 0) + batch.embedded,
          remaining: batch.remaining,
        }));
        if (!batch.has_more || batch.embedded === 0) break;
      } catch (err: any) {
        // Don't swallow — show the real failure so we can debug
        // VOYAGE_API_KEY / pgvector / network issues.
        setRunError(err?.message || String(err) || "Unknown error");
        break;
      }
    }
    setRunning(false);
    setDone(true);
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground leading-relaxed">
        One-shot setup for the semantic scorer. Embeds every job in your
        catalogue that doesn&apos;t yet have a vector — needed once after
        the migration runs. New jobs ingested after this get embedded
        inline during discovery; this button only matters for the
        historical catalogue. Test Voyage first if Voyage is freshly
        configured. Fix orphan descriptions if you bulk-imported before
        the heuristic-parser fallback shipped.
      </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={runBackfill} disabled={running}>
            {running ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Embedding…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                {done ? "Run again" : "Run backfill"}
              </>
            )}
          </Button>
          {totals && (running || done) && (
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <Stat label="Embedded" value={totals.embedded} tone="ok" />
              <Stat label="Remaining" value={totals.remaining} tone="muted" />
            </div>
          )}
        </div>
        {runError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/[0.06] p-3 text-xs">
            <p className="font-semibold text-destructive mb-1 flex items-center gap-1.5">
              <AlertCircle className="h-3.5 w-3.5" /> Backfill failed
            </p>
            <pre className="whitespace-pre-wrap break-words text-destructive/80 font-mono">
              {runError}
            </pre>
            {/* "Failed to fetch" is the browser's generic message when
                the response never arrives — almost always a Vercel 60s
                function timeout, not a Voyage / pgvector issue. */}
            {/Failed to fetch|NetworkError|timeout/i.test(runError) ? (
              <p className="text-muted-foreground mt-2 leading-relaxed">
                <span className="text-amber-300">Likely a Vercel function timeout</span> — the
                batch is running too long. Voyage and pgvector are probably fine
                (Test Voyage already confirmed). The button has been reduced
                to batches of 10; clicking <span className="text-foreground">Run again</span> should now
                succeed and chain through the catalogue.
              </p>
            ) : (
              <p className="text-muted-foreground mt-2 leading-relaxed">
                Usually one of: VOYAGE_API_KEY not set / wrong / expired,
                network timeout to Voyage, or pgvector package not installed
                on the Vercel build. Click <span className="text-foreground">Test Voyage</span> below to ping the embedding API directly and confirm.
              </p>
            )}
          </div>
        )}
        {!runError && totals && done && (
          <p className="text-xs text-muted-foreground">
            {totals.remaining === 0 && totals.embedded > 0
              ? "All jobs in the catalogue now have semantic vectors. The new scorer is fully active."
              : totals.embedded > 0
                ? `Embedded ${totals.embedded} jobs · ${totals.remaining} still need vectors (likely API rate limit — click Run again).`
                : "Backfill returned without embedding any jobs. Check Test Voyage below."}
          </p>
        )}

        <VoyageTestButton />
        <RawDescriptionFixButton />
    </div>
  );
}


function RawDescriptionFixButton() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const run = async () => {
    setRunning(true);
    setResult(null);
    try {
      const r = await api.post<{ backfilled: number }>(
        "/api/v1/auth/admin/fix/raw-description"
      );
      setResult({
        ok: true,
        detail:
          r.backfilled > 0
            ? `Fixed ${r.backfilled} job(s) — their raw_description was NULL. They can now be embedded.`
            : "No rows needed fixing. All jobs already have raw_description populated.",
      });
    } catch (e: any) {
      setResult({ ok: false, detail: e?.message || String(e) });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="pt-3 border-t border-white/[0.04] space-y-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-xs text-muted-foreground">
          Copy raw_content → raw_description for jobs the heuristic parser
          stored before the fallback fix. Run this before backfilling
          embeddings.
        </p>
        <Button variant="ghost" size="sm" onClick={run} disabled={running}>
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          Fix orphan descriptions
        </Button>
      </div>
      {result && (
        <div
          className={
            result.ok
              ? "rounded-md border border-emerald-500/30 bg-emerald-500/[0.06] p-2.5 text-xs text-emerald-300"
              : "rounded-md border border-destructive/30 bg-destructive/[0.06] p-2.5 text-xs text-destructive font-mono whitespace-pre-wrap break-words"
          }
        >
          {result.detail}
        </div>
      )}
    </div>
  );
}


interface CountryFilterDebugRow {
  job_id: string;
  title: string;
  company: string;
  country: string | null;
  location: string | null;
  remote_type: string | null;
  source: string | null;
  blocked_hits: string[];
  preferred_hits: string[];
  first_pass_keep: boolean;
  second_pass_keep: boolean;
  should_be_visible: boolean;
  sql_keeps?: boolean;
}

interface CountryFilterDebugResponse {
  preferred_countries: string[];
  preferred_countries_normalised: string[];
  remote_preference: string | null;
  target_roles: string[];
  blocked_names_count: number;
  preferred_names_count: number;
  sample_size: number;
  rows: CountryFilterDebugRow[];
  sql_disagreements?: { job_id: string; title: string; location: string | null; blocked_hits: string[] }[];
  compiled_sql?: string;
}

function CountryFilterDebugCard() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<CountryFilterDebugResponse | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const r = await api.get<CountryFilterDebugResponse>(
        "/api/v1/auth/admin/debug/country-filter?limit=30"
      );
      setData(r);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  // Only the rows the filter SHOULD drop are interesting — they reveal
  // the leak. We surface those first.
  const leaks = data?.rows.filter(r => !r.should_be_visible) ?? [];
  const kept = data?.rows.filter(r => r.should_be_visible) ?? [];

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Dumps your preferred_countries + the last 30 visible jobs with
        per-row filter trace. Use when the inbox keeps showing off-target
        jobs after you saved preferences.
      </p>
        <Button onClick={run} disabled={loading} size="sm">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Run diagnostic
        </Button>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/[0.06] p-2.5 text-xs text-destructive font-mono whitespace-pre-wrap break-words">
            {error}
          </div>
        )}

        {data && (
          <div className="space-y-3 text-xs">
            <div className="rounded-md border border-white/[0.06] bg-white/[0.02] p-3 space-y-1.5">
              <div>
                <span className="text-muted-foreground">preferred_countries:</span>{" "}
                <span className="font-mono">
                  {data.preferred_countries.length > 0
                    ? JSON.stringify(data.preferred_countries)
                    : <span className="text-destructive">(empty / null — filter does NOT run)</span>}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">remote_preference:</span>{" "}
                <span className="font-mono">{data.remote_preference || "(null)"}</span>
              </div>
              <div>
                <span className="text-muted-foreground">target_roles:</span>{" "}
                <span className="font-mono">{JSON.stringify(data.target_roles)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">filter knows:</span>{" "}
                <span className="font-mono">
                  {data.blocked_names_count} blocked, {data.preferred_names_count} preferred names/cities
                </span>
              </div>
            </div>

            {data.sql_disagreements && data.sql_disagreements.length > 0 && (
              <div className="rounded-md border border-destructive/40 bg-destructive/[0.06] p-3 space-y-1.5">
                <div className="text-destructive font-semibold">
                  ⚠ {data.sql_disagreements.length} SQL disagreement(s) — Python says drop, SQL keeps:
                </div>
                {data.sql_disagreements.map(d => (
                  <div key={d.job_id} className="text-destructive/90 text-xs font-mono">
                    {d.title} — location={JSON.stringify(d.location)} blocked_hits={JSON.stringify(d.blocked_hits)}
                  </div>
                ))}
                <div className="text-destructive/80 text-xs pt-1">
                  → Filter regex is not translating to Postgres correctly. Check compiled_sql below.
                </div>
              </div>
            )}

            {data.sql_disagreements && data.sql_disagreements.length === 0 && leaks.length > 0 && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/[0.06] p-3 text-emerald-300 text-xs">
                ✓ SQL filter agrees with Python — all {leaks.length} flagged row(s) are dropped at the DB. If you still see them in the inbox, force-refresh (cmd+shift+R) to bust the TanStack Query cache.
              </div>
            )}

            {leaks.length > 0 && (
              <div className="space-y-2">
                <div className="text-amber-300 font-semibold">
                  {leaks.length} row(s) the filter would DROP — leak details:
                </div>
                {leaks.map(r => <DebugRow key={r.job_id} row={r} />)}
              </div>
            )}

            {data.compiled_sql && (
              <details>
                <summary className="cursor-pointer text-muted-foreground text-xs">
                  Show compiled SQL (what Postgres receives)
                </summary>
                <pre className="mt-2 text-[10px] font-mono whitespace-pre-wrap break-all bg-black/40 p-2 rounded border border-white/[0.06] max-h-64 overflow-auto">
                  {data.compiled_sql}
                </pre>
              </details>
            )}

            {kept.length > 0 && (
              <details>
                <summary className="cursor-pointer text-muted-foreground">
                  {kept.length} row(s) the filter keeps — should be in your inbox
                </summary>
                <div className="space-y-2 mt-2">
                  {kept.map(r => <DebugRow key={r.job_id} row={r} />)}
                </div>
              </details>
            )}
          </div>
        )}
    </div>
  );
}

function DebugRow({ row }: { row: CountryFilterDebugRow }) {
  return (
    <div className="rounded-md border border-white/[0.06] bg-white/[0.02] p-2.5 font-mono">
      <div className="font-semibold text-foreground/90">
        {row.title} — {row.company}
      </div>
      <div className="text-muted-foreground mt-1">
        country={JSON.stringify(row.country)} {" · "}
        location={JSON.stringify(row.location)} {" · "}
        remote_type={JSON.stringify(row.remote_type)} {" · "}
        source={row.source}
      </div>
      <div className="mt-1">
        <span className="text-muted-foreground">blocked_hits:</span>{" "}
        <span className={row.blocked_hits.length > 0 ? "text-amber-300" : ""}>
          {JSON.stringify(row.blocked_hits)}
        </span>
        {"  "}
        <span className="text-muted-foreground">preferred_hits:</span>{" "}
        <span className={row.preferred_hits.length > 0 ? "text-emerald-300" : ""}>
          {JSON.stringify(row.preferred_hits)}
        </span>
      </div>
      <div className="mt-1">
        first_pass_keep=<span className={row.first_pass_keep ? "text-emerald-300" : "text-destructive"}>
          {String(row.first_pass_keep)}
        </span>{"  "}
        second_pass_keep=<span className={row.second_pass_keep ? "text-emerald-300" : "text-destructive"}>
          {String(row.second_pass_keep)}
        </span>{"  "}
        should_be_visible=<span className={row.should_be_visible ? "text-emerald-300" : "text-amber-300"}>
          {String(row.should_be_visible)}
        </span>
        {row.sql_keeps !== undefined && (
          <>{"  "}sql_keeps=<span className={row.sql_keeps === row.should_be_visible ? "text-emerald-300" : "text-destructive font-bold"}>
            {String(row.sql_keeps)}
          </span></>
        )}
      </div>
    </div>
  );
}


function VoyageTestButton() {
  const [pinging, setPinging] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const ping = async () => {
    setPinging(true);
    setResult(null);
    try {
      const r = await api.post<{ ok: boolean; dim?: number; sample?: number[]; error?: string }>(
        "/api/v1/auth/admin/embeddings/test"
      );
      if (r.ok) {
        setResult({
          ok: true,
          detail: `Voyage responded — vector dim ${r.dim}, first 3 floats: ${(r.sample ?? []).slice(0, 3).map(n => n.toFixed(3)).join(", ")}`,
        });
      } else {
        setResult({ ok: false, detail: r.error || "Unknown failure" });
      }
    } catch (e: any) {
      setResult({ ok: false, detail: e?.message || String(e) });
    } finally {
      setPinging(false);
    }
  };

  return (
    <div className="pt-3 border-t border-white/[0.04] space-y-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-xs text-muted-foreground">
          Embeds one test string. Confirms VOYAGE_API_KEY + network reach in &lt;5 s.
        </p>
        <Button variant="ghost" size="sm" onClick={ping} disabled={pinging}>
          {pinging ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          Test Voyage
        </Button>
      </div>
      {result && (
        <div
          className={
            result.ok
              ? "rounded-md border border-emerald-500/30 bg-emerald-500/[0.06] p-2.5 text-xs text-emerald-300"
              : "rounded-md border border-destructive/30 bg-destructive/[0.06] p-2.5 text-xs text-destructive font-mono whitespace-pre-wrap break-words"
          }
        >
          {result.detail}
        </div>
      )}
    </div>
  );
}


function Stat({ label, value, tone }: {
  label: string;
  value: number;
  tone: "default" | "ok" | "warn" | "muted";
}) {
  const color =
    tone === "ok" ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/[0.03]"
    : tone === "warn" ? "text-amber-400 border-amber-500/30 bg-amber-500/[0.03]"
    : tone === "muted" ? "text-muted-foreground border-white/[0.06] bg-white/[0.015]"
    : "text-foreground border-white/[0.08] bg-white/[0.02]";
  return (
    <div className={`rounded-md border px-2.5 py-1.5 ${color}`}>
      <div className="text-[10px] uppercase tracking-wider opacity-70">{label}</div>
      <div className="text-sm tabular-nums">{value}</div>
    </div>
  );
}
