import type { Metadata } from "next";
import Link from "next/link";
import { Contact, H2, LegalPage, List } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Terms of Service · FPL Copilot",
  description: "The terms for using the FPL Copilot app and website, including subscriptions and the free trial.",
};

const LINK = "font-medium text-purple-700 underline dark:text-purple-300";

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" updated="29 October 2026">
      <p>
        These terms apply when you use the FPL Copilot app or website (&ldquo;FPL Copilot&rdquo;, &ldquo;we&rdquo;).
        By creating an account or using the service you agree to them. Please also read our{" "}
        <Link className={LINK} href="/privacy">Privacy Policy</Link>.
      </p>

      <H2>The service</H2>
      <p>
        FPL Copilot gives Fantasy Premier League managers projections, transfer and captaincy suggestions, alerts
        and related tools, based on public FPL data and our own models. FPL Copilot is independent and is not made
        by, endorsed by or affiliated with the Premier League or Fantasy Premier League. Player, club and
        competition names belong to their owners.
      </p>
      <p>
        Our advice is a forecast, not a guarantee. Football is unpredictable, data can be late or wrong, and every
        decision about your team is yours. We are not responsible for points, ranks or prizes won or lost.
      </p>

      <H2>Your account and your team</H2>
      <List>
        <li>You need an Apple or Google account to sign in, and must be at least 13 years old.</li>
        <li>
          Connect only an FPL team that is yours. Each team can be connected to one FPL Copilot account at a time.
          If someone else has connected your team, you can take it back by proving you control it (we ask you to
          put a short code in your FPL team name).
        </li>
        <li>Keep your sign-in secure. You are responsible for what happens under your account.</li>
      </List>

      <H2>Free trial and subscriptions</H2>
      <List>
        <li>
          Your 30-day free trial starts when you first verify your FPL team. Each FPL team can have one free trial,
          ever, even if accounts are deleted and created again.
        </li>
        <li>
          After the trial, FPL Copilot Pro is a monthly or yearly auto-renewing subscription bought in the app
          through the App Store or Google Play. The price is shown in the app before you buy, in your local currency.
        </li>
        <li>
          Payment is taken by Apple or Google when you confirm the purchase. The subscription renews automatically
          at the end of each period unless you cancel at least 24 hours before it ends, and your account is charged
          for the renewal within 24 hours before the period ends.
        </li>
        <li>
          Cancel or manage your subscription in your App Store or Google Play account settings. Deleting the app or
          your FPL Copilot account does not cancel it. Cancelling stops the next renewal; you keep access until the
          end of the period you have paid for.
        </li>
        <li>
          Refunds are handled by Apple or Google under their policies; we cannot issue them ourselves.
        </li>
        <li>
          The website shows the same subscription; it does not sell one. If we change prices, the store tells you
          before the new price applies to you.
        </li>
      </List>

      <H2>Fair use</H2>
      <p>Please do not:</p>
      <List>
        <li>connect or try to take over teams that are not yours;</li>
        <li>scrape the service, call our server other than through the app or website, or overload it;</li>
        <li>try to get around the paywall, sign-in or security checks, or access other people&apos;s data;</li>
        <li>use FPL Copilot for anything unlawful, or resell or redistribute it.</li>
      </List>
      <p>We may suspend or close accounts that break these rules.</p>

      <H2>Availability and changes</H2>
      <p>
        We work to keep FPL Copilot running, but it depends on public FPL data and other services, so it may
        sometimes be unavailable, slow or wrong. We may change, add or remove features. If we ever stop offering
        the service, we will give notice in the app; store subscriptions can then be cancelled in your store
        settings.
      </p>

      <H2>Liability</H2>
      <p>
        FPL Copilot is provided &ldquo;as is&rdquo;. To the extent the law allows, we are not liable for indirect
        or consequential losses, or for losses arising from decisions you make using the service, and our total
        liability to you is limited to the amount you paid for the service in the 12 months before the claim.
        Nothing in these terms limits rights you have under consumer law that cannot be excluded.
      </p>

      <H2>App Store terms</H2>
      <p>
        If you downloaded the app from the App Store, Apple&apos;s{" "}
        <a className={LINK} href="https://www.apple.com/legal/internet-services/itunes/dev/stdeula/">
          Licensed Application End User License Agreement
        </a>{" "}
        also applies. Apple is not responsible for the app or its support, and these terms are between you and us.
      </p>

      <H2>Ending your account</H2>
      <p>
        You can delete your account at any time in the app under <strong>Profile → Delete account</strong>. What
        happens to your data is explained in the <Link className={LINK} href="/privacy">Privacy Policy</Link>.
      </p>

      <H2>Changes to these terms</H2>
      <p>
        We may update these terms. We will change the date above and, if the change is significant, let you know
        before it applies. Continuing to use FPL Copilot after that means you accept the new terms.
      </p>

      <H2>Contact</H2>
      <p>Questions about these terms: <Contact />.</p>
    </LegalPage>
  );
}
