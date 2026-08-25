import type { NextConfig } from "next";

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
};

export default nextConfig;
