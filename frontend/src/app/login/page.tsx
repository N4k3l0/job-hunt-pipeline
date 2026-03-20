"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Mail, Loader2, CheckCircle2 } from "lucide-react";

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
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Job Hunt Pipeline</CardTitle>
          <CardDescription>
            {sent
              ? "Check your email for the login link"
              : "Enter your email to receive a login link"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sent ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <CheckCircle2 className="h-10 w-10 text-emerald-400" />
              <p className="text-sm font-medium">Magic link sent!</p>
              <p className="text-xs text-muted-foreground text-center">
                We sent a login link to <strong>{email}</strong>. Click the link in your email to sign in.
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { setSent(false); setEmail(""); }}
                className="mt-2"
              >
                Use a different email
              </Button>
            </div>
          ) : (
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Mail className="h-4 w-4" />
                )}
                {loading ? "Sending..." : "Send login link"}
              </Button>
              <p className="text-xs text-muted-foreground text-center">
                Invite-only. Contact your admin if you don't have access.
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
