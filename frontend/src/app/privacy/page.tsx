import type { Metadata } from "next";
import Link from "next/link";
import { Contact, H2, LegalPage, List } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Privacy Policy · FPL Copilot",
  description: "What FPL Copilot collects, why, who processes it, and how to delete it.",
};

// Keep this in step with the code: a new table, provider or SDK that touches
// personal data needs a line here before it ships.
export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="29 October 2026">
      <p>
        FPL Copilot is an app and website that helps Fantasy Premier League managers with transfers, captaincy and
        team selection. This policy explains what we collect, why, and the choices you have. In short: we keep only
        what the service needs, we do not sell your data, and we run no advertising or tracking.
      </p>
      <p>
        FPL Copilot is independent. It is not made by or affiliated with the Premier League or Fantasy Premier
        League.
      </p>

      <H2>What we collect</H2>
      <List>
        <li>
          <strong>Your account.</strong> When you sign in with Apple or Google, we receive an account ID and your email
          address (Apple may give us a private relay address instead). Google may also share your name and profile
          picture. We use these only to sign you in and to contact you about your account.
        </li>
        <li>
          <strong>Your FPL team.</strong> The Team ID you connect, with the team and manager names shown on the
          Fantasy Premier League website. Using that ID we read the team&apos;s public FPL data: squad, transfers,
          chips, points and leagues. We never ask for your FPL password.
        </li>
        <li>
          <strong>Your subscription.</strong> Whether you are on a free trial or a subscription, the plan, the store
          it came from and when it renews or ends. Payments are handled entirely by Apple or Google; we never see
          your card or bank details.
        </li>
        <li>
          <strong>Notifications.</strong> If you allow them, your device&apos;s push notification token, the alerts
          you have turned on, and a record of which alerts we have sent so you do not get the same one twice. If you
          link Telegram, the chat ID that our bot sends messages to.
        </li>
        <li>
          <strong>Advice history.</strong> The recommendations we made for your team before each deadline, and how
          they turned out, so we can measure and show how accurate the advice is.
        </li>
        <li>
          <strong>Crash reports.</strong> When the app or server hits an error, a report of what went wrong (the
          error, the screen or request, the app version and device type). We remove your account details, email,
          IP address and sign-in tokens from these reports before they are sent.
        </li>
        <li>
          <strong>Server logs.</strong> Our servers briefly use your IP address to limit how often requests can be
          made, and our hosting providers keep standard request logs for a short time for security and debugging.
        </li>
      </List>
      <p>
        We do not use advertising, analytics or tracking tools, and we do not build profiles of you or sell or share
        your data for marketing.
      </p>

      <H2>Why we use it</H2>
      <p>
        To provide the service you signed up for (advice for your team, alerts, your subscription), to keep it
        secure and working, and to meet legal and accounting obligations. Where the law asks for a legal basis, it
        is the contract with you to provide FPL Copilot, and our legitimate interest in keeping the service secure
        and reliable.
      </p>

      <H2>Who processes it for us</H2>
      <p>We use these providers to run the service. Each only gets what it needs for its part:</p>
      <List>
        <li><strong>Supabase</strong>: sign-in and our database.</li>
        <li><strong>Render</strong> and <strong>Vercel</strong>: hosting for our server and this website.</li>
        <li><strong>Upstash</strong>: a short-lived cache in front of our server.</li>
        <li><strong>Apple</strong> and <strong>Google</strong>: sign-in, in-app purchases and push notification delivery.</li>
        <li><strong>RevenueCat</strong>: keeps track of App Store and Google Play subscriptions.</li>
        <li><strong>Expo</strong>: delivers push notifications to your device.</li>
        <li><strong>Sentry</strong>: crash and error reports.</li>
        <li><strong>Telegram</strong>: only if you link it, to deliver alerts there.</li>
      </List>
      <p>
        Some of these providers process data outside your country, including in the United States, under their own
        data protection commitments. We read public data from the Fantasy Premier League website but send it nothing
        about you.
      </p>

      <H2>How long we keep it</H2>
      <p>
        We keep your data while you have an account. When you delete your account we delete your account, connected
        team, notification settings, devices, advice history and subscription status. We keep only:
      </p>
      <List>
        <li>a record that a team has used its free trial (the Team ID and dates, no longer linked to you), so a
          trial cannot be restarted;</li>
        <li>store purchase records with your account details removed, which may be needed for accounting;</li>
        <li>a record that your account ID was deleted, so it cannot be recreated by mistake.</li>
      </List>
      <p>
        Crash reports and server logs are deleted automatically by those providers after a limited period.
      </p>

      <H2>Deleting your account</H2>
      <p>
        In the app, go to <strong>Profile → Delete account</strong>. This deletes your data as described above and
        your sign-in. It does not cancel a store subscription: cancel that in your App Store or Google Play
        settings. You can also ask us to delete your account by writing to <Contact />.
      </p>

      <H2>Your rights</H2>
      <p>
        Depending on where you live, you can ask to see the data we hold about you, correct it, delete it, receive a
        copy, or object to how we use it. Write to <Contact /> and we will reply within 30 days. You can also
        complain to your local data protection authority.
      </p>

      <H2>Security</H2>
      <p>
        Data travels over encrypted connections. Sign-in tokens are kept in your device&apos;s secure storage. The
        app and website reach your data only through our server, which checks every request against your own
        account; the database tables are closed to direct access.
      </p>

      <H2>Children</H2>
      <p>
        FPL Copilot is not intended for children under 13 and we do not knowingly collect their data. If you think
        a child has given us data, contact us and we will delete it.
      </p>

      <H2>Changes</H2>
      <p>
        If we change this policy we will update the date above and, if the change is significant, let you know
        before it applies. See also our <Link className="font-medium text-purple-700 underline dark:text-purple-300" href="/terms">Terms of Service</Link>.
      </p>

      <H2>Contact</H2>
      <p>Questions about privacy: <Contact />.</p>
    </LegalPage>
  );
}
