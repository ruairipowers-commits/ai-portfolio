# Lil'Helper — the phone app

Expo (React Native, TypeScript). One codebase for iPhone (first) and Android (later). It talks to the household's own
Lil'Helper server (`helper serve`); the phone keeps only the sign-in token, in the iPhone Keychain.

Screens: **This week** (the plan by day, swap any meal, approve), **Shopping** (one list per store: an Instacart link,
a list to share to the Whole Foods app or Reminders, an aisle-ordered Trader Joe's list), **Jobs** (who cooks,
washes up, sets the table, helps and feeds the dog; tap to hand a job on), **After meals** (how much was eaten, a
star rating), **Home** (savings so far, Google Calendar feed, fridge printouts, specials from a flyer photo).

## Run it

```bash
npm install
npm run typecheck
npx expo start          # scan the QR code with Expo Go on the phone, or press w for the web version
```

Point it at a server on the sign-in screen ("Your household's server"), or set `EXPO_PUBLIC_API_URL`.
Locally: `helper serve` in the project folder, then use `http://<your-computer's-address>:8650`.

## Onto an iPhone with TestFlight

Needs an Apple Developer Program membership ($99 a year) and an Expo account (free). No Mac or Xcode needed:
EAS builds in the cloud.

1. `npx eas-cli@latest login`, then `npx eas-cli@latest init` (links the project; writes the project id).
2. In `eas.json`, set `EXPO_PUBLIC_API_URL` under `production` to the household server's address.
3. `npx eas-cli@latest build --platform ios --profile production` — EAS asks for your Apple ID once and creates the
   signing certificate and the app record (`com.agentls.lilhelper`).
4. `npx eas-cli@latest submit --platform ios --latest` uploads it to App Store Connect.
5. In App Store Connect → TestFlight, add your wife as an internal tester. She installs **TestFlight** from the App
   Store, accepts the invite, and installs Lil'Helper.

Sign-in links open the app through the `lilhelper://` scheme. Android later:
`npx eas-cli@latest build --platform android` from the same code.
