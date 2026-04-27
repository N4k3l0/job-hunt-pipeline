import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  // Supabase sometimes returns the error directly in the URL when the link
  // itself is bad (expired, wrong redirect, etc). Forward those to the login
  // page so the user can see what happened.
  const supaError = searchParams.get("error");
  const supaErrorCode = searchParams.get("error_code");
  const supaErrorDescription = searchParams.get("error_description");

  if (supaError || supaErrorCode) {
    const params = new URLSearchParams();
    params.set("error", supaError || supaErrorCode || "auth_failed");
    if (supaErrorDescription) params.set("detail", supaErrorDescription);
    return NextResponse.redirect(`${origin}/login?${params.toString()}`);
  }

  if (!code) {
    return NextResponse.redirect(
      `${origin}/login?error=missing_code&detail=${encodeURIComponent(
        "No auth code in callback URL — the magic link may have been opened twice."
      )}`,
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

  // Forward the precise error message so we can debug from the browser URL.
  const params = new URLSearchParams();
  params.set("error", "exchange_failed");
  params.set("detail", error.message || "unknown");
  if ("status" in error && error.status) params.set("status", String(error.status));
  return NextResponse.redirect(`${origin}/login?${params.toString()}`);
}
