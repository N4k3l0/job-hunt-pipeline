import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Auth callback. Handles two Supabase flows:
 *
 * 1. PKCE flow (?code=...) — used by `signInWithOtp` from our login form.
 *    Server-side: exchange code for session cookie, redirect to /dashboard.
 *
 * 2. Implicit / hash-token flow (#access_token=...&refresh_token=...) —
 *    used by Supabase's admin `generate_link` API. The fragment never
 *    reaches the server; we return an HTML page with inline JS that reads
 *    window.location.hash, calls supabase.auth.setSession(), then routes
 *    to /dashboard.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const supaError = searchParams.get("error");
  const supaErrorCode = searchParams.get("error_code");
  const supaErrorDescription = searchParams.get("error_description");

  if (supaError || supaErrorCode) {
    const params = new URLSearchParams();
    params.set("error", supaError || supaErrorCode || "auth_failed");
    if (supaErrorDescription) params.set("detail", supaErrorDescription);
    return NextResponse.redirect(`${origin}/login?${params.toString()}`);
  }

  // === PKCE flow ===
  if (code) {
    const cookieStore = await cookies();
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return cookieStore.getAll();
          },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          },
        },
      }
    );
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}/dashboard`);
    }
    const params = new URLSearchParams();
    params.set("error", "exchange_failed");
    params.set("detail", error.message || "unknown");
    if ("status" in error && error.status) params.set("status", String(error.status));
    return NextResponse.redirect(`${origin}/login?${params.toString()}`);
  }

  // === Implicit flow (no `?code=` in URL) ===
  // The hash fragment is invisible server-side. Return an HTML page with
  // inline JS that reads the hash and POSTs the tokens to our
  // /auth/set-session route, which uses @supabase/ssr to write the session
  // into HTTP cookies. (Calling setSession client-side via @supabase/
  // supabase-js writes only to localStorage, which the middleware that
  // gates /dashboard cannot see — that's why the page used to flash
  // "Signing you in…" then bounce the user back to /login.)
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Signing in…</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0a0a0a;color:#a3a3a3;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
  .box{text-align:center}
  .err{color:#f87171;max-width:420px;margin:1rem auto;font-size:14px;line-height:1.5}
  .spin{display:inline-block;width:16px;height:16px;border:2px solid #404040;
        border-top-color:#a3a3a3;border-radius:50%;animation:s 0.8s linear infinite;
        vertical-align:middle;margin-right:8px}
  @keyframes s{to{transform:rotate(360deg)}}
</style></head>
<body><div class="box" id="status"><span class="spin"></span>Signing you in…</div>
<script>
  (async () => {
    const fail = (msg) => {
      const u = new URL("/login", window.location.origin);
      u.searchParams.set("error", "callback_hash_failed");
      u.searchParams.set("detail", msg);
      window.location.replace(u.toString());
    };
    try {
      const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
      const params = new URLSearchParams(hash);
      const at = params.get("access_token");
      const rt = params.get("refresh_token");
      const errDesc = params.get("error_description") || params.get("error");
      if (errDesc) { return fail(errDesc); }
      if (!at || !rt) {
        return fail("No auth code or session token in callback URL — the magic link may have been opened twice or expired.");
      }
      const r = await fetch("/auth/set-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access_token: at, refresh_token: rt }),
        credentials: "include",
      });
      if (!r.ok) {
        let detail = "set_session_failed";
        try { detail = (await r.json()).detail || detail; } catch {}
        return fail(detail);
      }
      window.history.replaceState(null, "", window.location.pathname);
      window.location.replace("/dashboard");
    } catch (e) {
      fail((e && e.message) || String(e));
    }
  })();
</script></body></html>`;
  return new NextResponse(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}
