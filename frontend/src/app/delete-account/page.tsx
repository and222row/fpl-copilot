import type { Metadata } from "next";
import Link from "next/link";
import { CONTACT_EMAIL, H2, LegalPage, List } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Delete your account · FPL Copilot",
  description: "How to delete your FPL Copilot account and data, in the app or without it.",
};

const LINK = "font-medium text-purple-700 underline dark:text-purple-300";

// Google Play requires a page where people can ask for deletion without the
// app; this is the URL given in the Play Console's Data safety form. Email
// requests are carried out from /admin (Delete user), which runs the same
// deletion as the app.
export default function DeleteAccountPage() {
  const mailto = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Delete my FPL Copilot account")}`;
  return (
    <LegalPage title="Delete your FPL Copilot account" updated="29 October 2026">
      <H2>In the app</H2>
      <p>
        Open FPL Copilot, go to <strong>Profile → Delete account</strong> and confirm. Your account and data are
        deleted straight away.
      </p>

      <H2>Without the app</H2>
      <p>
        Email{" "}
        <a className={LINK} href={mailto}>
          {CONTACT_EMAIL}
        </a>{" "}
        with the subject <strong>Delete my FPL Copilot account</strong>. Send it from the email address of the
        Apple or Google account you sign in with (we use it to confirm the account is yours) and include your
        FPL Team ID if you have one connected. We delete the account within 30 days, usually much sooner, and
        reply to confirm.
      </p>

      <H2>What is deleted</H2>
      <List>
        <li>your sign-in account and email address;</li>
        <li>your connected FPL team, notification settings, devices and alert history;</li>
        <li>your advice history and subscription status.</li>
      </List>

      <H2>What is kept</H2>
      <List>
        <li>a record that the team has used its free trial (Team ID and dates, no longer linked to you), so a trial
          cannot be restarted;</li>
        <li>store purchase records with your account details removed, which may be needed for accounting;</li>
        <li>a record that your account ID was deleted.</li>
      </List>
      <p>
        Crash reports and server logs contain no account details and are deleted automatically by our providers
        after a limited period. Details are in the <Link className={LINK} href="/privacy">Privacy Policy</Link>.
      </p>

      <H2>Your subscription</H2>
      <p>
        Deleting your account does not cancel an App Store or Google Play subscription. Cancel it in your store
        subscription settings so you are not charged again.
      </p>
    </LegalPage>
  );
}
