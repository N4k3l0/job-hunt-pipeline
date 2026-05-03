import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  // Force the IMPLICIT flow instead of the default PKCE.
  //
  // Why: PKCE stores a code_verifier cookie on the device that called
  // signInWithOtp(). When the user opens the magic link from a different
  // browser / device — common for "request on laptop, tap on phone" —
  // that cookie isn't there and the exchange returns
  //   exchange_failed: PKCE code verifier not found in storage.
  //
  // Implicit flow returns tokens in the URL hash fragment instead, so the
  // link works on any device. Our /auth/callback route already handles
  // BOTH shapes (?code=… for PKCE, #access_token=… for implicit) so
  // there's no extra wiring needed.
  //
  // Trade-off: tokens briefly appear in the URL fragment. For an
  // invite-only app with 2–5 users this is acceptable; the bigger UX
  // win of cross-device magic links outweighs it.
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { auth: { flowType: "implicit" } },
  );
}
