# Lil'Helper — the phone app

Expo (React Native, TypeScript). One codebase for iPhone (first) and Android (later). It talks to the household's own
Lil'Helper server (`helper serve`); the phone keeps only the sign-in token, in the iPhone Keychain.

First run: sign in with your email, then the **welcome wizard** sets up a household (people and invites, dinner
times and who's home, nights off, stores and cards, fridge and freezer, shopping trips, calendar and notifications)
and plans the first week. An invite link brings someone straight into an existing household.

Tabs: **This week** (the plan by day; swap a meal; tap a day to make it takeout, leftovers or a freezer night, or to
say who's out; buy ahead on a sale; approve), **Shopping** (one list per trip or store, with its day, who's going and
the card to use), **Jobs**, **Rate** (how much was eaten, a star rating), **Money** (budget vs planned vs spent; add
spending, import a card statement, read a receipt), **Home** (people, dinners, meal style, stores and cards, trips,
fridge and freezer, recipes, specials, cook from what I've got, ingredient forecast, cost report, calendar and
notifications, account). The admin changes settings; everyone can see them.

Code: `src/app/` (screens; `house/` holds the Home screens), `src/lib/api.ts` (every server call, typed),
`src/lib/push.ts` (notifications and tap-to-open), `src/components/` (form pieces, shared wizard parts).

## Run it

```bash
npm install
npm run typecheck
npx expo start          # scan the QR code with Expo Go on the phone, or press w for the web version
```

Point it at a server on the sign-in screen ("Use my own server"), or set `EXPO_PUBLIC_API_URL`.
Locally: `helper serve` in the project folder, then use `http://<your-computer's-address>:8650`.

## Onto an iPhone with TestFlight

Step by step, with the server on the EVO-X1 first: [../docs/household-setup.md](../docs/household-setup.md).

Needs an Apple Developer Program membership ($99 a year) and an Expo account (free). No Mac or Xcode needed:
EAS builds in the cloud.

1. `npx eas-cli@latest login`, then `npx eas-cli@latest init` (links the project; writes the project id).
2. In `eas.json`, set `EXPO_PUBLIC_API_URL` under `production` to the household server's address.
3. `npx eas-cli@latest build --platform ios --profile production` — EAS asks for your Apple ID once and creates the
   signing certificate, the push key (say yes to push notifications) and the app record (`com.agentls.lilhelper`).
4. `npx eas-cli@latest submit --platform ios --latest` uploads it to App Store Connect.
5. In App Store Connect → TestFlight, add your wife as an internal tester. She installs **TestFlight** from the App
   Store, accepts the invite, and installs Lil'Helper.

Sign-in links open the app through the `lilhelper://` scheme. Android later:
`npx eas-cli@latest build --platform android` from the same code.
