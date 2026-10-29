import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

/** Where people write about privacy, deletion or the terms. */
export const CONTACT_EMAIL = "and222row@gmail.com";

export function Contact() {
  return (
    <a className="font-medium text-purple-700 underline dark:text-purple-300" href={`mailto:${CONTACT_EMAIL}`}>
      {CONTACT_EMAIL}
    </a>
  );
}

/** The shared frame of the privacy policy and the terms: plain, readable text. */
export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8 sm:py-12">
      <Link href="/" className="inline-flex items-center gap-2">
        <Image src="/logo.svg" alt="" width={32} height={32} />
        <span className="font-bold text-slate-900 dark:text-slate-100">FPL Copilot</span>
      </Link>
      <h1 className="mt-8 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-50">{title}</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Last updated {updated}</p>
      <div className="mt-6 space-y-4 text-[15px] leading-relaxed text-slate-700 dark:text-slate-300">{children}</div>
    </main>
  );
}

export function H2({ children }: { children: ReactNode }) {
  return <h2 className="!mt-8 text-lg font-semibold text-slate-900 dark:text-slate-100">{children}</h2>;
}

export function List({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-2 pl-5">{children}</ul>;
}
