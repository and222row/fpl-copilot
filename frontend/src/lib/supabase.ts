import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Browser-only, created on first use: the page is prerendered on the server,
// where there is no session to read and nothing should touch storage.
//
// The session lives in localStorage, as it must for a browser-only app. That
// is reachable by any script on the page, which is why next.config.ts sets a
// Content-Security-Policy restricting where the page may connect.
let client: SupabaseClient | null = null;

export function supabaseConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_KEY);
}

export function supabase(): SupabaseClient {
  if (!client) {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const key = process.env.NEXT_PUBLIC_SUPABASE_KEY;
    if (!url || !key) {
      throw new Error("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_KEY must be set");
    }
    client = createClient(url, key, {
      auth: {
        // Authorization-code flow with PKCE: the redirect carries a one-time
        // code, not tokens in the URL fragment.
        flowType: "pkce",
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  }
  return client;
}
