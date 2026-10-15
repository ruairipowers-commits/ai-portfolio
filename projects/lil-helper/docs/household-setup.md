# Setting up Lil'Helper

Two parts: **A** runs the server on the EVO-X1 behind your Cloudflare domain (about 30 minutes), **B** puts the app on
the iPhones through TestFlight (about an hour, most of it waiting for Apple and Expo). Do A first: the app needs the
server. After that, everything about your household (people, dinners, stores, trips, recipes) is set up **in the
app**: the welcome wizard walks you through it, and you invite your family from there.

How it fits together:

```
iPhone (Lil'Helper app) ─┐
Calendar apps (feeds)  ──┼─▶ https://helper.agentls.com ─▶ Cloudflare ══ tunnel ══ cloudflared ─▶ lil-helper:8650
Calendar tap-back links ─┘    (public HTTPS; every request                                         on the EVO-X1
                               except sign-in, health, feeds                                       volume lilhelper-data:
                               and signed links needs a session)                                   accounts + one folder
                                                                                                    per household
```

The server is reachable from the internet so phones work anywhere and Google Calendar can fetch the feed, but
nothing in it is readable without signing in: sign-in is by an emailed one-time link, a session belongs to one
household, calendar feeds are private unguessable URLs (each person can replace theirs), and the one-tap links in
calendar events are signed and expire. Starting a new household needs a sign-up code while you're the only user.

This is separate from the public demo stack (`deploy/selfhost`, demos.agentls.com), which runs the demo on a fictional
family. It only shares the Cloudflare tunnel.

---

## A. The server (on the EVO-X1)

Run everything in this part **on the EVO-X1**, over SSH from the Mac.

### A1. Get the code

```bash
cd ~/ai-portfolio && git pull
ls projects/lil-helper/Dockerfile        # should exist
```

### A2. Secrets and settings

These live outside the repo, so a `git pull` never touches them.

```bash
mkdir -p ~/lil-helper-home && chmod 700 ~/lil-helper-home
cat > ~/lil-helper-home/.env <<EOF
HELPER_SECRET=$(openssl rand -hex 32)
HELPER_PUBLIC_URL=https://helper.agentls.com
HELPER_APP_LINK=lilhelper://signin
HELPER_SIGNUP=invite
HELPER_SIGNUP_CODES=$(openssl rand -hex 6)
HELPER_PUSH=expo
RESEND_API_KEY=re_xxxxxxxx
HELPER_MAIL_FROM=Lil'Helper <helper@agentls.com>
EOF
chmod 600 ~/lil-helper-home/.env
nano ~/lil-helper-home/.env                         # paste your real Resend key
grep HELPER_SIGNUP_CODES ~/lil-helper-home/.env     # note the code: you type it once, in the welcome wizard
```

| Setting | What it does |
|---|---|
| `HELPER_SECRET` | Signs sign-in links, sessions, calendar feeds and tap links. Changing it signs everyone out and changes every calendar link |
| `HELPER_PUBLIC_URL` | The address in calendar feeds and tap links |
| `HELPER_SIGNUP` | `invite`: a new household needs a code from `HELPER_SIGNUP_CODES` (comma-separated); joining by invite always works. `open` when the app goes public; `closed` to stop new households |
| `HELPER_PUSH=expo` | Sends push notifications through Expo's push service. Without it they're written to a file instead |
| `EXPO_ACCESS_TOKEN` | Only if you turn on "enhanced push security" for the project on expo.dev |
| `RESEND_API_KEY`, `HELPER_MAIL_FROM` | Sign-in links, invites and the weekly email. The sender must be on the domain you verified in Resend (falls back to the shared `MAIL_FROM`) |

### A3. Build and start it

```bash
cd ~/ai-portfolio/projects/lil-helper
docker build -t lil-helper .                                  # 3–5 minutes the first time

docker run -d --name lil-helper --restart unless-stopped \
  -p 127.0.0.1:8650:8650 \
  --env-file ~/lil-helper-home/.env \
  -v lilhelper-data:/app/warehouse \
  --memory 1g --cpus 2 --pids-limit 200 --cap-drop ALL --security-opt no-new-privileges \
  lil-helper

curl -s http://127.0.0.1:8650/api/health          # {"ok":true,…,"signup":"invite"}
docker logs lil-helper | tail -5                  # "Application startup complete"
```

The scheduler runs inside it: every 15 minutes it checks each household, in its own time zone, for what's due
(Saturday's draft, the weekly email, Wednesday's restock check, a reminder an hour before each shopping trip, and
"how was dinner?" a little after dinner). Each happens once, even across restarts.

### A4. Put it on the tunnel

The demos' `cloudflared` container already runs a tunnel. Let it reach Lil'Helper by name:

```bash
NET=$(docker inspect $(docker ps -qf name=cloudflared) -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | awk '{print $1}')
echo $NET                                         # e.g. generated_default
docker network connect "$NET" lil-helper
```

Then in the Cloudflare dashboard: **Zero Trust → Networks → Tunnels → ai-portfolio-demos → Public hostnames → Add**:
subdomain `helper`, domain `agentls.com`, path empty, **service `HTTP` → `lil-helper:8650`**. Save.

Check from the Mac: `https://helper.agentls.com/api/health`.

Recommended, in **Security → WAF → Rate limiting rules** (free plan includes one): 60 requests a minute per IP on
`helper.agentls.com`. The server also limits sign-in requests per address and per email.

### A5. Already using v1 (a household.yaml)?

Bring it in once, and you're its admin:

```bash
docker run --rm --env-file ~/lil-helper-home/.env -v lilhelper-data:/app/warehouse \
  -v ~/lil-helper-home/household.yaml:/tmp/household.yaml:ro \
  lil-helper helper household import /tmp/household.yaml --email you@example.com --person ruairi
```

`--person` is your id in the file. From then on, change settings in the app (the file is no longer read). Skip
this for a fresh start: the welcome wizard creates the household.

### Updating the server later

```bash
cd ~/ai-portfolio && git pull
cd projects/lil-helper && docker build -t lil-helper . && docker rm -f lil-helper
# …then the same `docker run -d …` as A3, and `docker network connect "$NET" lil-helper` again.
```

**Alexa (optional):** follow [alexa.md](alexa.md) once; it adds `HELPER_ALEXA_SKILL_ID` to `.env`.

Back up: `docker run --rm -v lilhelper-data:/d -v ~/lil-helper-home:/b alpine tar czf /b/lilhelper-$(date +%F).tgz -C /d .`

---

## B. The iPhone app (from the Mac)

You need: the Apple Developer membership, a free Expo account (**expo.dev → Sign up**), and Node.js on the Mac
(`node -v` v20 or later; if not, `brew install node`).

### B1. Get the code

```bash
cd ~/Documents/AIPF/ai-portfolio && git pull          # or wherever your clone is
cd projects/lil-helper/app
npm install
```

### B2. (Optional) Try it in the browser or Expo Go first

`npx expo start --web` opens the app in a browser; `npx expo start` and scan the QR code with Expo Go on the iPhone.
On the sign-in screen, tap **Use my own server** and enter `https://helper.agentls.com`. In Expo Go the emailed link
can't open the app directly: long-press it, **Copy**, and paste it into **Opened the email on another device?**.
Push notifications and the microphone only work in the real build (B5); in Expo Go, use the microphone on the
iPhone keyboard instead. A version that adds a native module (v4 added speech recognition) needs a new build (B5–B7),
not just a reload.

### B3. Link the project to Expo

```bash
npx eas-cli@latest login
npx eas-cli@latest init           # creates the project and adds its id to app.json (push needs it)
```

### B4. Point the build at your server

`eas.json` → `build.production.env.EXPO_PUBLIC_API_URL` → `https://helper.agentls.com`.

### B5. Build in the cloud

```bash
npx eas-cli@latest build --platform ios --profile production
```

Answer the prompts: log in to your Apple account → your team → let EAS register `com.agentls.lilhelper` and generate
the certificate and profile → **"Set up Push Notifications?" yes** (EAS creates the Apple push key; Expo's push
service uses it, nothing to put on the server). The build takes 15–25 minutes.

### B6. Send it to App Store Connect

```bash
npx eas-cli@latest submit --platform ios --latest
```

If "Lil'Helper" is taken as an App Store name, use something like "Lil'Helper Family" (the home-screen name stays
"Lil'Helper"). Apple processes the build for 10–30 minutes and emails you.

### B7. Testers

**App Store Connect → Users and Access → +** → your wife's Apple ID email (role Marketing). Then **Apps →
Lil'Helper → TestFlight → Internal Testing → +** → a group ("Family") → add her and you → add the build. She
installs **TestFlight**, opens the invite → **Accept** → **Install**.

---

## C. First run (in the app)

1. **You:** open Lil'Helper → your email → **Email me a sign-in link** → tap the link. The welcome wizard starts.
2. **Welcome → Start my household:** household name, your first name, time zone (filled in from the phone), and the
   sign-up code from A2. You're the household's **admin**.
3. **Who's in it:** add your wife (adult, her email → **Add and invite**) and your son (child, age, allergies). Kids
   don't need the app; add an email only if they'll use it (they can see the plan and their jobs, and rate meals).
4. **Dinners:** which days, usual time, and who's usually home each night.
5. **Nights off:** any regular takeout, eating-out, leftovers or freezer nights, and what takeout and eating out cost.
6. **Stores and money:** where you shop, memberships (Prime, Costco, Instacart+), the cards you pay with (names only),
   the weekly budget and the most a dinner should cost per serving.
7. **Kitchen:** fridge and freezer size, cooking extra for the freezer, and a kid chef night.
8. **Shopping trips:** your regular trips (day, time, store, in store / pickup / delivery, who goes), or skip and let
   Lil'Helper choose each week.
9. **Stay in the loop:** **Add to Apple Calendar** (or Google), and **Turn on notifications**.
10. **Plan this week now.**

**Your wife:** she gets an email "Ruairi invited you to … on Lil'Helper". She installs the app from TestFlight, then
taps **join the household** in the email (or signs in with that email): she lands straight in the household as an
adult. She does step 9 for her own phone; her calendar shows her dinners, her jobs and the trips she's on.

**Then:** add everyone's birthday in **More → People** (it decides child or adult, gives teens adult portions, takes
birthday people off jobs, and puts birthdays in **Special occasions**). To enter a lot at once — recipes, what's in
the freezer, the brands you buy — use **More → Import and export**: download the workbook, fill it in, upload it,
check the preview, confirm.

Everything in the wizard is under **More** later. Only the admin changes settings and people; any adult can plan,
swap, change a night, add specials and recipes, approve and record spending.

---

## If something doesn't work

| Symptom | Check |
|---|---|
| App can't reach the server | `https://helper.agentls.com/api/health` in Safari. If that fails: `docker ps` (running?), the tunnel's public hostname, and `docker network connect` (A4) after any re-create |
| Tapping the sign-in link doesn't open the app | Long-press → **Copy**, paste into **Opened the email on another device?** |
| No sign-in email | `docker exec lil-helper helper mail-test you@example.com` sends a test and prints exactly what happened. `refused (403)… not verified`: the sender in `HELPER_MAIL_FROM` must be on a domain verified in Resend (resend.com → Domains). `RESEND_API_KEY not set`: add it to `.env` and re-create the container. Also check spam, and that you haven't asked more than 5 times in an hour |
| "A sign-up code is needed" | Use a code from `HELPER_SIGNUP_CODES`, or ask the admin to invite you |
| Invite link says "expired" or "for a different email" | Invites last 14 days and only work for the invited address; the admin sends it again from **People** |
| No notifications | **More → Calendar and notifications** shows the state; iPhone **Settings → Lil'Helper → Notifications**; `HELPER_PUSH=expo` on the server; the build had push set up (B5) |
| Calendar not updating | Apple refreshes subscribed calendars about hourly, Google every few hours. **Make a new private link** if a link was shared by mistake |
| Container keeps restarting | `docker logs lil-helper` — usually a missing `HELPER_SECRET` |
| Microphone button missing | It only shows where speech recognition is available: the TestFlight/App Store build (not Expo Go), or Chrome/Safari on the web. iPhone **Settings → Lil'Helper**: Microphone and Speech Recognition on |
| Alexa says "link Lil'Helper first" | **More → Alexa → Get a code**, then enable the skill in the Alexa app and type the code (ten minutes, once). Each person links their own |
| Weekly email not arriving | The email day and time in settings, and `docker logs lil-helper` |
