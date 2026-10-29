import type { Metadata } from "next";
import Link from "next/link";
import { Contact, H2, LegalPage, List } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Help and Support · FPL Copilot",
  description: "Answers to common questions about FPL Copilot, and how to contact us.",
};

const LINK = "font-medium text-purple-700 underline dark:text-purple-300";

// The App Store and Google Play listings link here as the support URL. Keep
// the answers in step with the app: menu names are quoted as they appear.
export default function SupportPage() {
  return (
    <LegalPage title="Help and Support" updated="29 October 2026">
      <p>
        Something not working, or a question we don&apos;t answer below? Email <Contact /> with your FPL Team ID
        and what you were doing, and we&apos;ll get back to you, usually within two working days.
      </p>

      <H2>Getting started</H2>
      <p>
        <strong>Where do I find my FPL Team ID?</strong> Sign in at{" "}
        <a className={LINK} href="https://fantasy.premierleague.com">fantasy.premierleague.com</a> and open the{" "}
        <strong>Points</strong> page. Your Team ID is the number after <code>/entry/</code> in the address, for
        example <code>/entry/1234567/event/9</code>. In the app, <strong>Where do I find my Team ID?</strong> under
        the Team ID field shows the same steps.
      </p>
      <p>
        <strong>Can I look before signing up?</strong> Yes. On the sign-in screen, tap{" "}
        <strong>Not sure yet? Have a look at your team first</strong> and enter your Team ID.
      </p>
      <p>
        <strong>Do you need my FPL password?</strong> No, never. FPL Copilot only reads the public data FPL
        publishes for every team.
      </p>

      <H2>Your team</H2>
      <p>
        <strong>It says my team is already connected to another account.</strong> Each FPL team can be connected
        to one FPL Copilot account. If the team is yours, tap <strong>It&apos;s my team: take it over</strong>: the
        app gives you a short code to add to your team name on the FPL website. Save it,
        tap verify, and the team moves to you. You can change the name back afterwards.
      </p>
      <p>
        <strong>The advice ignores transfers I&apos;ve just made.</strong> FPL doesn&apos;t publish transfers until
        the gameweek deadline passes, so we can&apos;t see them before then. Go to <strong>Transfers → Record
        transfers you made</strong> and enter them, and all advice uses your updated squad straight away.
      </p>
      <p>
        <strong>How do I change team?</strong> <strong>Profile → Disconnect team</strong>, then connect the new
        Team ID.
      </p>

      <H2>Free trial and subscription</H2>
      <List>
        <li>
          <strong>How does the free trial work?</strong> You get 30 days of FPL Copilot Pro free once you verify
          your team by adding a short code to its name on the FPL website (the app shows you how). Each FPL team
          can have one free trial.
        </li>
        <li>
          <strong>How do I subscribe?</strong> In the app, <strong>Profile → Upgrade to Pro</strong>. Payment goes
          through the App Store or Google Play.
        </li>
        <li>
          <strong>How do I cancel?</strong> In your App Store or Google Play subscription settings (in the app:{" "}
          <strong>Profile → Manage subscription</strong>). Cancel at least 24 hours before the renewal date. You
          keep Pro until the end of the period you paid for. Deleting the app or your account does not cancel it.
        </li>
        <li>
          <strong>I paid but Pro isn&apos;t unlocked, or I have a new phone.</strong> Sign in with the same Apple or
          Google account, then <strong>Profile → Restore purchases</strong>.
        </li>
        <li>
          <strong>Can I get a refund?</strong> Refunds are handled by Apple (
          <a className={LINK} href="https://reportaproblem.apple.com">reportaproblem.apple.com</a>) or Google Play
          (your Play Store order history). We can&apos;t issue them ourselves.
        </li>
        <li>
          <strong>Can I use Pro on the website?</strong> Yes. Sign in on{" "}
          <Link className={LINK} href="/">this website</Link> with the same account. Subscriptions are only sold in
          the app.
        </li>
      </List>

      <H2>Notifications</H2>
      <p>
        <strong>Profile → Notifications</strong> turns on alerts for injuries and availability, price changes,
        deadline reminders, and goals and full time during matches. If nothing arrives, check that notifications are allowed for
        FPL Copilot in your phone&apos;s settings. On the website you can also get the same alerts in Telegram.
      </p>

      <H2>Accuracy</H2>
      <p>
        Advice is based on projections from public FPL data. It&apos;s a forecast, not a guarantee, and every
        decision is yours. <strong>Track record</strong> in the app shows how past advice has actually turned out.
      </p>

      <H2>Your account and data</H2>
      <p>
        To delete your account and data, go to <strong>Profile → Delete account</strong>, or{" "}
        <Link className={LINK} href="/delete-account">ask us without the app</Link>. What we keep, and why,
        is in the <Link className={LINK} href="/privacy">Privacy Policy</Link>. The rules for using FPL Copilot
        are in the <Link className={LINK} href="/terms">Terms of Service</Link>.
      </p>

      <H2>Contact</H2>
      <p>
        Email <Contact />. FPL Copilot is independent and not affiliated with the Premier League or Fantasy
        Premier League, so questions about your FPL account itself (password, points, prizes) go to FPL.
      </p>
    </LegalPage>
  );
}
