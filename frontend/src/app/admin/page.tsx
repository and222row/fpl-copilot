import type { Metadata } from "next";
import { AdminApp } from "@/components/admin/AdminApp";

export const metadata: Metadata = {
  title: "Admin · FPL Copilot",
  // Not a page for search engines; access is enforced by the API either way.
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return <AdminApp />;
}
