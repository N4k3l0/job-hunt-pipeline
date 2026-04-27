"use client";

import { useState } from "react";
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

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const supabase = createClient();
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      });

      if (error) {
        if (error.message.includes("rate") || error.message.includes("limit")) {
          setError("Please wait 60 seconds before requesting another link.");
        } else {
          setError(error.message);
        }
        return;
      }

      setSent(true);
    } catch {
      setError("An unexpected error occurred");
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
        {/* Brand mark + name + tagline */}
        <div className="text-center space-y-3">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-500/20 bg-amber-500/5 shadow-[0_0_24px_rgba(251,191,36,0.15)]">
            <Sparkles className="h-5 w-5 text-amber-400" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Job Hunt Pipeline</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Smarter applications, less noise.
            </p>
          </div>
        </div>

        <Card className="border-white/[0.06] shadow-2xl shadow-black/40">
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
                <p className="text-xs text-muted-foreground/70">
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
                    {error}
                  </div>
                )}
                <Button
                  type="submit"
                  className="w-full h-11 text-base sm:text-sm font-semibold"
                  disabled={loading || !email.trim()}
                >
                  {loading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Sending link…
                    </>
                  ) : (
                    <>
                      Send sign-in link
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
                <p className="text-xs text-muted-foreground/70 text-center leading-relaxed">
                  We'll email you a one-time link. No password required.
                </p>
              </form>
            )}
          </CardContent>
        </Card>

        <p className="text-center text-xs text-muted-foreground/50">
          Invite-only · Contact your admin if you don't have access
        </p>
      </div>
    </div>
  );
}
