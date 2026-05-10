"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Mail, Loader2, CheckCircle2, ArrowRight, Sparkles, ArrowLeft,
} from "lucide-react";

// Supabase's per-email OTP rate limit is ~60s. We use 65s as our
// client-side gate so we never fire a second request inside the
// server's window — that's what was causing the countdown to re-trigger
// every cycle (we'd hit 0, the user would click, Supabase would still
// be in its window, return rate-limited, and we'd reset to 60).
const COOLDOWN_SECONDS = 65;
const COOLDOWN_KEY = "jhp:lastOtpAt";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  // Remaining cooldown in seconds. Derived from a localStorage timestamp
  // so it survives page refreshes — without that, refreshing reset the
  // counter to 0 and the next click immediately re-tripped Supabase.
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    const cbError = sp.get("error");
    const cbDetail = sp.get("detail");
    if (cbError) {
      setError(cbDetail ? `${cbError}: ${cbDetail}` : `Sign-in failed: ${cbError}`);
    }
    // Restore cooldown from a previous attempt in this browser.
    const lastAt = Number(localStorage.getItem(COOLDOWN_KEY) || 0);
    if (lastAt > 0) {
      const remaining = COOLDOWN_SECONDS - Math.floor((Date.now() - lastAt) / 1000);
      if (remaining > 0) setCooldown(remaining);
    }
  }, []);

  // Tick the cooldown down once a second.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    if (cooldown > 0) return; // belt-and-braces against double-submit
    setError("");
    setLoading(true);

    // Stamp the attempt FIRST so a refresh / accidental double-submit
    // can't slip through the cooldown gate.
    try {
      localStorage.setItem(COOLDOWN_KEY, String(Date.now()));
    } catch { /* private mode etc. */ }
    setCooldown(COOLDOWN_SECONDS);

    try {
      const supabase = createClient();
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      });

      if (error) {
        // Don't restart the cooldown on a rate-limit error — our local
        // gate already prevents future submits for ~65s. Just show what
        // Supabase said for any non-rate-limit error.
        const isRateLimit =
          error.message.includes("rate") || error.message.includes("limit");
        if (!isRateLimit) {
          setError(error.message);
          // Failure other than rate-limit means no email was sent — clear
          // the cooldown so the user can retry immediately.
          setCooldown(0);
          try { localStorage.removeItem(COOLDOWN_KEY); } catch { /* ignore */ }
        }
        return;
      }

      setSent(true);
    } catch {
      setError("An unexpected error occurred");
      setCooldown(0);
      try { localStorage.removeItem(COOLDOWN_KEY); } catch { /* ignore */ }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden flex items-center justify-center px-4 py-12">
      {/* Single warm wash from the top so the page doesn't feel flat. No grid,
          no second glow — anything more competes with the form. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 70% 45% at 50% -10%, rgba(251,191,36,0.08), transparent 70%)",
        }}
      />

      <div className="w-full max-w-sm space-y-8">
        {/* Brand mark + name + tagline. Stagger entry: icon first, then
            title, tagline, card. Each row delays ~80ms after the previous
            so the eye lands on one thing at a time — Emil's cascading
            entry. The icon also pulses on entry (scale 0.85 → 1) which
            mirrors the "balloon with shape even when deflated" rule. */}
        <div className="text-center space-y-3">
          <div className="login-stagger-pop inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-500/20 bg-amber-500/5 shadow-[0_0_24px_rgba(251,191,36,0.15)]">
            <Sparkles className="h-5 w-5 text-amber-400" />
          </div>
          <div className="space-y-1">
            <h1 className="login-stagger font-display text-3xl font-semibold tracking-tight [animation-delay:80ms]">Job Hunt Pipeline</h1>
            <p className="login-stagger text-sm text-muted-foreground [animation-delay:160ms]">
              Smarter applications, less noise.
            </p>
          </div>
        </div>

        <Card className="login-stagger border-white/[0.06] shadow-2xl shadow-black/40 [animation-delay:240ms]">
          <CardContent className="p-6">
            {sent ? (
              <div className="flex flex-col items-center text-center gap-4 py-2">
                <div className="relative">
                  <div className="absolute inset-0 rounded-full bg-emerald-500/20 blur-xl" />
                  <div className="relative inline-flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10 border border-emerald-500/20">
                    <CheckCircle2 className="h-7 w-7 text-emerald-400" />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-base font-semibold">Check your email</p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    We sent a sign-in link to{" "}
                    <span className="font-medium text-foreground">{email}</span>.
                  </p>
                </div>
                <p className="text-sm text-muted-foreground">
                  The link works once and expires in 1 hour.
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setSent(false); setEmail(""); setError(""); }}
                  className="mt-1 text-muted-foreground hover:text-foreground"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Use a different email
                </Button>
              </div>
            ) : (
              <form onSubmit={handleLogin} className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-xs uppercase tracking-wider text-muted-foreground">
                    Email
                  </Label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/50" />
                    <Input
                      id="email"
                      type="email"
                      autoComplete="email"
                      placeholder="you@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                      autoFocus
                      className="h-11 pl-10 text-base sm:text-sm"
                    />
                  </div>
                </div>
                {error && (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/[0.08] px-3 py-2 text-sm text-destructive">
                    {cooldown > 0
                      ? `Wait ${cooldown}s before requesting another link.`
                      : error}
                  </div>
                )}
                <Button
                  type="submit"
                  className="w-full h-11 text-base sm:text-sm font-semibold"
                  disabled={loading || !email.trim() || cooldown > 0}
                >
                  {loading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Sending link…
                    </>
                  ) : cooldown > 0 ? (
                    <>Try again in {cooldown}s</>
                  ) : (
                    <>
                      Send sign-in link
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
                <p className="text-sm text-muted-foreground text-center leading-relaxed">
                  We'll email you a one-time link. No password required.
                </p>
              </form>
            )}
          </CardContent>
        </Card>

        <p className="login-stagger text-center text-sm text-muted-foreground [animation-delay:320ms]">
          Invite-only · Contact your admin if you don't have access
        </p>
      </div>

      {/* Stagger keyframes scoped to the page so they don't leak globally.
          Strong custom ease per Emil. Reduced-motion users skip the
          movement entirely but still see the final composition. */}
      <style jsx global>{`
        .login-stagger {
          opacity: 0;
          transform: translateY(8px);
          animation: login-fadeup 480ms cubic-bezier(0.23, 1, 0.32, 1) both;
        }
        .login-stagger-pop {
          opacity: 0;
          transform: scale(0.85);
          animation: login-pop 520ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
        }
        @keyframes login-fadeup {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes login-pop {
          from { opacity: 0; transform: scale(0.85); }
          to   { opacity: 1; transform: scale(1); }
        }
        @media (prefers-reduced-motion: reduce) {
          .login-stagger, .login-stagger-pop {
            animation: none;
            opacity: 1;
            transform: none;
          }
        }
      `}</style>
    </div>
  );
}
