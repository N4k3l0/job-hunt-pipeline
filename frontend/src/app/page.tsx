"use client";

import { useEffect } from "react";

/**
 * Root page. Two responsibilities:
 *
 * 1. If the URL has a magic-link hash fragment (#access_token=...) — which
 *    happens when Supabase's allowlist forces the redirect to land at the
 *    Site URL (root) instead of /auth/callback — preserve it and forward
 *    to /auth/callback so the existing handler can process it.
 *
 * 2. Otherwise, just route to /dashboard (middleware handles the auth gate).
 *
 * This is a client component because hash fragments are invisible to the
 * server. The route handler at /auth/callback expects the hash on its own
 * URL, so we just preserve it during the forward.
 */
export default function Home() {
  useEffect(() => {
    const hash = window.location.hash || "";
    if (hash.includes("access_token") || hash.includes("error_description")) {
      window.location.replace(`/auth/callback${hash}`);
    } else {
      window.location.replace("/dashboard");
    }
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
      Redirecting…
    </div>
  );
}
