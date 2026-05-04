import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * POST /auth/set-session
 *
 * Why this exists: the implicit-flow callback returns hash tokens
 * (#access_token=…&refresh_token=…) which only the browser can read.
 * Our previous client-side setSession() used @supabase/supabase-js
 * standalone, which writes the session to LOCALSTORAGE — invisible to
 * the rest of our app's server-side middleware that reads cookies via
 * @supabase/ssr. End result: user appeared "signed in" client-side but
 * /dashboard's middleware saw no session cookie and bounced back to
 * /login.
 *
 * This server route accepts the hash tokens via POST, calls setSession
 * on the @supabase/ssr server client, and writes the session into
 * proper auth cookies. Then the client JS can safely redirect to
 * /dashboard knowing middleware will recognize the session.
 */
export async function POST(request: NextRequest) {
  let body: { access_token?: string; refresh_token?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const { access_token, refresh_token } = body || {};
  if (!access_token || !refresh_token) {
    return NextResponse.json(
      { ok: false, error: "missing_tokens" },
      { status: 400 },
    );
  }

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
            cookieStore.set(name, value, options),
          );
        },
      },
    },
  );

  const { error } = await supabase.auth.setSession({
    access_token,
    refresh_token,
  });
  if (error) {
    return NextResponse.json(
      { ok: false, error: "set_session_failed", detail: error.message },
      { status: 401 },
    );
  }
  return NextResponse.json({ ok: true });
}
