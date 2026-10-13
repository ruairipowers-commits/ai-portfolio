# Setting up Lil'Helper for your household

Two parts: **A** runs the household server on the EVO-X1 (about 30 minutes), **B** puts the app on the iPhones
through TestFlight (about an hour, most of it waiting for Apple and Expo). Do A first: the app needs the server.

How it fits together:

```
iPhone (Lil'Helper app) ── Tailscale ──▶ https://<evo-x1>.<tailnet>.ts.net ──▶ 127.0.0.1:8650 on the EVO-X1
                                          (tailscale serve: private HTTPS,      └─ docker container "lil-helper"
                                           only devices on your tailnet)           household.yaml (read-only)
                                                                                    volume lilhelper-data (database)
```

The household server is **not** part of the public demo stack (`deploy/selfhost`, demos.agentls.com). That stack
runs the public demo on a fictional family; this one holds your family's data and is reachable only over Tailscale.
Nothing about it is public: no Cloudflare hostname, nothing open on the router.

---

## A. The household server (on the EVO-X1)

Run everything in this part **on the EVO-X1**, over SSH from the Mac (`ssh <you>@<evo-x1 tailscale name or IP>`).

### A1. Get the code

The deploy clone used by the demos is at `~/ai-portfolio`. Pull it:

```bash
cd ~/ai-portfolio && git pull
ls projects/lil-helper/Dockerfile        # should exist
```

### A2. A private folder for your household's file and secrets

This lives outside the repo, so a `git pull` never touches it and nothing in it can be committed.

```bash
mkdir -p ~/lil-helper-home && chmod 700 ~/lil-helper-home
cp ~/ai-portfolio/projects/lil-helper/config/household.example.yaml ~/lil-helper-home/household.yaml
chmod 644 ~/lil-helper-home/household.yaml     # the container's user must be able to read it
nano ~/lil-helper-home/household.yaml
```

Edit it for your family (the example is the fictional Rivera family):

| Section | What to set |
|---|---|
| `household` | `name`, `budget_per_week`, `planning_minutes_before` (your honest estimate; it's the time-saved baseline) |
| `people` | One entry per person. Adults: `age_band: adult`, `can_cook: true`, and **`email`** — that's the address the sign-in link goes to, so use the one each of you reads on the iPhone. Kids: `age_band: kid` and `age`. `allergies` uses these names only: `peanut`, `tree_nut`, `dairy`, `egg`, `gluten`, `soy`, `fish`, `shellfish`, `sesame`. `likes` / `dislikes` are optional (recipe ids from `data/recipes.yaml`) |
| `pets` | Your dog: name, weight, food brand, cups a day, bag size, `kcal_per_day` from the bag, and `vet_notes` for anything your vet said to avoid |
| `meals` | Which meals to plan on which days; `special_nights` for leftovers or eating out |
| `prep_minutes`, `batch_day` | Hands-on cooking minutes you'll accept each day |
| `stores`, `home_store`, `memberships` | Which stores you use, and `instacart_plus`, `amazon_prime`, `costco` |
| `cards` | Names only (never numbers); their credits go in `config/money.yaml` |
| `outputs.email` | Day, time and both of your addresses for the Sunday email |

### A3. Secrets

```bash
cat > ~/lil-helper-home/.env <<EOF
HELPER_SECRET=$(openssl rand -hex 32)
RESEND_API_KEY=re_xxxxxxxx
MAIL_FROM=Lil'Helper <helper@agentls.com>
HELPER_APP_LINK=lilhelper://signin
EOF
chmod 600 ~/lil-helper-home/.env
nano ~/lil-helper-home/.env        # paste your real Resend key
```

`MAIL_FROM` must be an address on the domain you verified in Resend. Changing `HELPER_SECRET` later signs everyone
out and changes the calendar-feed link.

### A4. Build and check your household file

```bash
cd ~/ai-portfolio/projects/lil-helper
docker build -t lil-helper .                                  # 3–5 minutes the first time

# A dry run on your real file: prints a week's plan, then exits. Fix household.yaml until this works.
docker run --rm -v ~/lil-helper-home/household.yaml:/app/config/household.yaml:ro lil-helper helper plan --no-ideas
```

### A5. Start it

```bash
docker run -d --name lil-helper --restart unless-stopped \
  -p 127.0.0.1:8650:8650 \
  --env-file ~/lil-helper-home/.env \
  -v ~/lil-helper-home/household.yaml:/app/config/household.yaml:ro \
  -v lilhelper-data:/app/warehouse \
  --memory 1g --cpus 2 --pids-limit 200 --cap-drop ALL --security-opt no-new-privileges \
  lil-helper

curl -s http://127.0.0.1:8650/api/health          # {"ok":true,"version":"0.1.0"}
docker logs lil-helper | tail -5                  # "Application startup complete"
```

It listens on 127.0.0.1 only: Docker skips ufw for published ports, so binding to loopback is what keeps it off
your LAN. It restarts with the machine. The Saturday draft, Sunday email and Wednesday restock check run inside it.

### A6. Private HTTPS over Tailscale

One-time, in the Tailscale admin console (login.tailscale.com) → **DNS**: turn on **MagicDNS** and **HTTPS
Certificates**. Then on the EVO-X1:

```bash
sudo tailscale serve --bg 8650
tailscale serve status        # shows https://<machine>.<tailnet>.ts.net → http://127.0.0.1:8650
```

From the Mac (with Tailscale on), open `https://<machine>.<tailnet>.ts.net/api/health`. **Write that URL down**:
it's the server address for the app.

### A7. Let your wife's iPhone reach it

Tailscale admin console → **Users → Invite users** → her email. She installs **Tailscale** from the App Store,
signs in with that account, and leaves it on. (Your own iPhone too, if you'll use the app.)

### Updating the server later

```bash
cd ~/ai-portfolio && git pull
cd projects/lil-helper && docker build -t lil-helper . && docker rm -f lil-helper
# …then the same `docker run -d …` command as A5. The database is in the volume, so nothing is lost.
```

Back up the database: `docker run --rm -v lilhelper-data:/d -v ~/lil-helper-home:/b alpine tar czf /b/lilhelper-$(date +%F).tgz -C /d .`

---

## B. The iPhone app (from the Mac)

You need: the Apple Developer membership (you have it), a free Expo account (**expo.dev → Sign up**), and Node.js
on the Mac (`node -v` should print v20 or later; if not, `brew install node`).

### B1. Get the code on the Mac

```bash
cd ~/Documents/AIPF/ai-portfolio && git pull          # or wherever your clone is
cd projects/lil-helper/app
npm install
```

### B2. (Optional, 5 minutes) Try it on your own iPhone first

Install **Expo Go** and **Tailscale** on your iPhone (Tailscale on). Then on the Mac:

```bash
npx expo start
```

Scan the QR code with the iPhone camera. In the app, set **Your household's server** to the `https://….ts.net`
URL from A6, type your email, and tap **Email me a sign-in link**. In Expo Go the link in the email can't open the
app directly: long-press it, **Copy**, and paste it into **Opened the email on another device?**. Plan a week, swap
a meal, approve. Stop with Ctrl-C when done.

### B3. Link the project to Expo

```bash
npx eas-cli@latest login          # your Expo account
npx eas-cli@latest init           # "Would you like to create a project?" → yes. Adds the project id to app.json
```

### B4. Point the build at your server

Edit `eas.json` → `build.production.env.EXPO_PUBLIC_API_URL` → your `https://….ts.net` URL from A6. (She can also
change it on the sign-in screen, but this way she never has to.)

### B5. Build in the cloud

```bash
npx eas-cli@latest build --platform ios --profile production
```

Answer the prompts:
- **Log in to your Apple account?** Yes → your Apple ID and the 2-factor code.
- **Team:** your developer team.
- **Bundle identifier** `com.agentls.lilhelper`: let EAS register it.
- **Distribution certificate / provisioning profile:** let EAS generate them.

The build takes 15–25 minutes on Expo's servers; the terminal (and expo.dev) shows progress.

### B6. Send it to App Store Connect

```bash
npx eas-cli@latest submit --platform ios --latest
```

Log in with your Apple ID again. If there's no app record yet, EAS creates one in App Store Connect. App names are
unique across the whole App Store: if "Lil'Helper" is taken, use something like "Lil'Helper Family" (the name on
her home screen stays "Lil'Helper"). Apple then processes the build for 10–30 minutes and emails you when it's ready.
Encryption export compliance is already answered in `app.json`, so the build won't wait on that question.

### B7. Invite your wife as a tester

In **App Store Connect** (appstoreconnect.apple.com):
1. **Users and Access → +** → her name and Apple ID email → role **Marketing** → Invite. She accepts the email.
2. **Apps → Lil'Helper → TestFlight → Internal Testing → +** → create a group (e.g. "Family") → add her (and you)
   → add the build.

She gets an email from TestFlight. On her iPhone: install **TestFlight** from the App Store, open the invite →
**Accept** → **Install**.

### B8. Her first sign-in

1. Tailscale on.
2. Open Lil'Helper → type her email (the one in `household.yaml`) → **Email me a sign-in link**.
3. Tap the link in the email on the iPhone; it opens Lil'Helper signed in (for 30 days).
4. **This week → Plan this week** (or wait for Saturday's draft), swap anything, **Approve**.
5. **Home → Copy the Google Calendar feed link**, then on the iPhone: **Settings → Calendar → Accounts → Add
   Account → Other → Add Subscribed Calendar** → paste. The phone fetches the feed itself over Tailscale, so the
   meals, cooks and dish-washers appear in her Calendar app and update on their own.

   **Google Calendar can't subscribe to it** while the server is private: Google fetches subscribed calendars from its
   own servers, which can't reach a Tailscale address. To get it into Google Calendar, Lil'Helper would need to push
   events through the Google Calendar API (documented as the next option, not built yet).

### Later builds

TestFlight builds expire after 90 days. After a change: `npx eas-cli@latest build --platform ios --profile production`
then `npx eas-cli@latest submit --platform ios --latest`; testers get the update in TestFlight.

---

## If something doesn't work

| Symptom | Check |
|---|---|
| App says it can't reach the server | Tailscale on? Open the `https://….ts.net/api/health` URL in Safari on the phone |
| Tapping the sign-in link doesn't open the app | Long-press the link → **Copy**, then paste it into **Opened the email on another device?** on the sign-in screen |
| No sign-in email | `docker logs lil-helper`; `RESEND_API_KEY` and `MAIL_FROM` in `~/lil-helper-home/.env`; the email must match an **adult** in `household.yaml` |
| Container keeps restarting | `docker logs lil-helper` — usually a missing `HELPER_SECRET` or a typo in `household.yaml` (run the A4 dry run) |
| "Only an adult can approve" | That person needs `age_band: adult` in `household.yaml` |
| Sunday email not arriving | `docker exec lil-helper helper job email` sends it now and prints what happened |
