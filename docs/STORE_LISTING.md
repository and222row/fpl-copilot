# Store listing and review

What to paste into App Store Connect and the Google Play Console, and how to
set up the account the reviewers use. Release steps are in
[DEPLOYMENT.md](DEPLOYMENT.md#release-checklist); store products and
RevenueCat in [PAYMENTS.md](PAYMENTS.md#setup-checklist).

**The repo is public.** Fill the placeholders (`<…>`) in the store consoles
only. Never commit the review FPL account's password.

## URLs

| Field | Value |
|---|---|
| Support URL | `https://fpl-copilot-three.vercel.app/support` |
| Marketing URL (optional) | `https://fpl-copilot-three.vercel.app` |
| Privacy Policy URL | `https://fpl-copilot-three.vercel.app/privacy` |
| Terms of Use (EULA) | `https://fpl-copilot-three.vercel.app/terms` |
| Account deletion (Play Data safety) | `https://fpl-copilot-three.vercel.app/delete-account` |
| Contact email | `and222row@gmail.com` |

## The review team

Reviewers sign in with their own Apple or Google account, so the thing to
prepare is an FPL team for them to connect:

1. Create a separate FPL account (a new email address, not yours) at
   fantasy.premierleague.com and pick a squad. Name the team, say,
   "Copilot Review". Note its Team ID (Points page, the number after
   `/entry/`).
2. Each FPL team can be connected to one FPL Copilot account at a time. Before
   **every** submission, open `/admin` on the website, search for the review
   Team ID and use **Release their team**, so the reviewer can connect it.
3. The free trial needs the team verified (a code in its team name), and each
   team gets one trial ever. So the first reviewer can start the trial with
   the FPL login below; later reviewers will see the paywall and buy with
   their sandbox account, which costs nothing. Both paths are in the notes.

## App Review notes (App Store Connect → App Review Information)

Sign-in required: **yes**. Leave the demo user name and password empty
(sign-in is Sign in with Apple or Google only) and paste this into **Notes**,
filling the three placeholders:

```text
FPL Copilot helps Fantasy Premier League (FPL) managers choose transfers,
captains and their starting XI, with live gameweek scores and alerts. It reads
the public data FPL publishes for each team; it is independent and not
affiliated with the Premier League.

HOW TO REVIEW
1. Sign in with Apple (or Google) using any account.
   (To look around without an account first: on the sign-in screen tap
   "Not sure yet? Have a look at your team first" and enter the Team ID below.)
2. When asked for an FPL Team ID, enter: <REVIEW_TEAM_ID>
3. Pro features (advice, planner, alerts) need a free trial or subscription:
   a) Free trial: on the paywall tap "Start my free trial". The app shows a
      short code. Sign in at https://fantasy.premierleague.com with
         email:    <FPL_REVIEW_EMAIL>
         password: <FPL_REVIEW_PASSWORD>
      open Pick Team, scroll to Admin, tap Team Details, add the code to the
      team name and save. Then tap Verify in the app. This starts a 30-day
      free trial.
   b) If the trial has already been used by a previous review, the paywall
      appears instead: subscribe with your sandbox account (monthly or
      yearly auto-renewing subscription, sold only through in-app purchase).

OTHER POINTS
- Restore purchases and Manage subscription: Profile tab.
- Account deletion: Profile > Delete account (deletes the account and data;
  the app explains that a store subscription must be cancelled separately).
- Push notifications are optional and only sent for the user's own team.
- Player data comes from FPL's public API. Live scores update during
  Premier League matches; between matches they show the latest results.
- Contact: and222row@gmail.com
```

## Google Play: App access

Play Console → App content → **App access** → *All or some functionality is
restricted* → add instructions. Use the same text as above, with "Sign in with
Google" first and "license tester account" in place of "sandbox account".

## Listing text

### App Store

| Field | Text |
|---|---|
| Name (30) | `FPL Copilot` |
| Subtitle (30) | `Transfers, captain and alerts` |
| Category | Sports (secondary: Utilities or none) |
| Age rating | 4+: no gambling (FPL is free to play), no user content |
| Keywords (100) | `fantasy football,soccer,transfers,captain,gameweek,mini league,wildcard,chips,price changes` |

Keep "Premier League" out of the keywords and the subtitle: App Review treats
other companies' trademarks in metadata as grounds for rejection (guidelines
2.3.7 and 5.2). "FPL" in the name is the one deliberate exception, explained by
the independence line in the description.

Promotional text (170, editable without a new build):

```text
Live gameweek scores, your mini-league as it happens, and transfer and captain advice built for your own FPL team. Start with a 30-day free trial.
```

Description:

```text
FPL Copilot is your assistant for Fantasy Premier League. Connect your team
with its Team ID and get advice built around your actual squad, budget and
free transfers.

TRANSFERS AND CAPTAINCY
• The best transfers for your squad, with the points they should gain
• Captain and vice-captain picks, and your best starting XI and bench
• A multi-week transfer planner, and when to play your chips

LIVE GAMEWEEK
• Live points with bonus and automatic substitutions as they happen
• Your mini-leagues re-ranked live, plus head-to-head leagues and the cup
• The players who will swing your league this week

NEWS AND ALERTS
• Injuries, suspensions and returns for the players you own
• Price changes before they happen
• Goals, assists and red cards for your players, your rival's captain, and a
  deadline reminder with your recommended moves

AND MORE
• Fixture planner with difficulty ratings, double and blank gameweeks
• Transfer trends: who managers are buying and selling
• A review of every gameweek, shareable cards, and a track record showing
  how the advice actually performed

FPL COPILOT PRO
Start with a 30-day free trial. After that, FPL Copilot Pro is an
auto-renewing monthly or yearly subscription. Payment is charged to your
Apple ID account at confirmation of purchase. The subscription renews
automatically unless cancelled at least 24 hours before the end of the
current period, and your account is charged for renewal within 24 hours
before the end of the period. Manage or cancel it in your App Store account
settings.

Terms of Use: https://fpl-copilot-three.vercel.app/terms
Privacy Policy: https://fpl-copilot-three.vercel.app/privacy

FPL Copilot is independent and is not affiliated with, endorsed by or
connected to the Premier League or Fantasy Premier League.
```

### Google Play

| Field | Text |
|---|---|
| App name (30) | `FPL Copilot` |
| Short description (80) | `Transfer and captain advice, live scores and alerts for your FPL team.` |
| Full description | The App Store description above, with "Apple ID account" and "App Store account settings" changed to "Google Play account" and "Google Play subscriptions". |
| Category | Sports |
| Contact email | `and222row@gmail.com` |

## Privacy answers

From [the privacy policy](https://fpl-copilot-three.vercel.app/privacy); keep
the two in step.

### App Store: App Privacy

Tracking: **No**. Every type below is used for *App Functionality* only.

| Data type | Linked to the user | Notes |
|---|---|---|
| Contact Info → Email Address | yes | From Sign in with Apple or Google. |
| Contact Info → Name | yes | Only if Google shares it. |
| Identifiers → User ID | yes | Account ID; the FPL Team ID. |
| Purchases → Purchase History | yes | Subscription status and plan. |
| Diagnostics → Crash Data | no | Sentry, identity removed. |
| Diagnostics → Performance Data | no | Sentry, identity removed. |

Not collected: location, contacts, health, financial info (the stores take
payment), browsing history, usage data, advertising data.

### Google Play: Data safety

- Collects data: **yes**. Shares data: **no** (service providers acting for
  us do not count as sharing).
- Encrypted in transit: **yes**. Users can request deletion: **yes** (in the
  app, and by email).
- Types, all *App functionality*, none optional except where noted:
  Personal info → Email address, Name (optional); App activity → none;
  App info and performance → Crash logs, Diagnostics; Financial info →
  Purchase history; Device or other IDs → none (the push token is used only to
  deliver notifications the user turned on; declare it here if Play's form asks).
