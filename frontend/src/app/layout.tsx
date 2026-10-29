import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FPL Copilot",
  description:
    "AI-powered Fantasy Premier League decision platform — projections, transfers, captaincy and alerts for your squad.",
};

// Next sets the viewport meta tag itself, so only the colouring is declared
// here. Deliberately no `maximumScale`/`userScalable` — blocking pinch-zoom
// would make the dense tables unreadable for anyone who needs to magnify them.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
  colorScheme: "light dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <footer className="mt-auto flex justify-center gap-5 px-4 py-6 text-xs text-slate-500 dark:text-slate-400">
          <Link href="/privacy" className="hover:underline">Privacy Policy</Link>
          <Link href="/terms" className="hover:underline">Terms of Service</Link>
        </footer>
      </body>
    </html>
  );
}
