import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

function origin(url: string | undefined): string {
  try {
    return url ? new URL(url).origin : "";
  } catch {
    return "";
  }
}

// The Supabase session sits in localStorage, readable by any script that runs
// here. connect-src is the part that matters for that: even injected script
// can only talk to this site, the API and Supabase, not post a token
// elsewhere. Inline scripts are allowed because the page is statically
// prerendered, and nonces would need every request rendered dynamically.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data: https://resources.premierleague.com",
  "font-src 'self'",
  `connect-src 'self' ${origin(process.env.NEXT_PUBLIC_API_URL) || "http://localhost:8000"} ${origin(process.env.NEXT_PUBLIC_SUPABASE_URL)}`.trim(),
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const nextConfig: NextConfig = {
  images: {
    // FPL serves player headshots from its own CDN. Next 16 takes URL objects
    // here rather than the older { protocol, hostname, pathname } form.
    remotePatterns: [
      new URL(
        "https://resources.premierleague.com/premierleague/photos/players/**",
      ),
    ],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
