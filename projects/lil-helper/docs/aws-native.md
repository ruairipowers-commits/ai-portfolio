# Production: Lil'Helper in the cloud

Today Lil'Helper runs on one machine at home (the EVO-X1) behind Cloudflare, with sign-up by invite code. That's
right for one family and a few testers. Releasing it on the App Store, where anyone can download it, start a
subscription and set up their own household, needs a hosted service. The code is already multi-household; this is
the path from here to there.

## Three stages

| Stage | Who | Where it runs | Sign-up |
|---|---|---|---|
| **1. Now** | Your family | EVO-X1, `helper.agentls.com` via the Cloudflare Tunnel | `HELPER_SIGNUP=invite` with a code |
| **2. Beta** | A few families on TestFlight (external testing, up to 10,000 testers) | Same, plus nightly off-site backups | Invite codes per family |
| **3. App Store** | Anyone | AWS (below) | `HELPER_SIGNUP=open`, subscription required to start a household |

Stage 2 needs no new code. Stage 3 needs the database move, subscriptions and the privacy work below.

## What's already built for many households

- **Accounts and households:** a central accounts database (users, households, members with roles, invites, push
  devices); each household's plans, recipes, spending and settings in their own database. Every request runs inside
  one household chosen by its session, and a session can't be pointed at another household (tested).
- **Roles:** admin, adult, kid, enforced on every endpoint.
- **In-app account deletion** (App Store Review Guideline 5.1.1(v) requires it) and admin deletion of a household.
- **Per-household time zones** for the scheduler, reminders and calendar feeds.
- **Sign-up modes** (`invite`, `open`, `closed`) and the welcome wizard, which already shows where the subscription
  step goes.

## AWS shape

```
iPhone / Android ─▶ CloudFront + WAF ─▶ App Runner (or ECS Fargate): the FastAPI container, 2+ instances
                                            │
            ┌───────────────┬───────────────┼─────────────────┬──────────────────┬───────────────┐
      Aurora Serverless   S3 (flyer &     SES (sign-in,    EventBridge         Secrets         Bedrock
      v2 Postgres:        receipt photos,  invites,         Scheduler → one     Manager         (ideas, notes,
      accounts + all      1-day lifecycle; weekly email)    "tick" Lambda per   (HELPER_SECRET,  flyer/receipt
      household tables,   PDFs, 7-day)                      15 min, fans out    Expo token)      reading, by
      row-level security                                    by household                         alias)
```

| Piece today | In AWS | Change needed |
|---|---|---|
| SQLite per household + `accounts.sqlite` | Aurora Postgres, one schema, `household_id` on every household table, **row-level security** policies on `current_setting('app.household_id')` | The tenant ContextVar sets `SET LOCAL app.household_id` per request instead of choosing a file; store.py moves to SQLAlchemy Core. RLS means a missed `WHERE` can't leak another family's rows |
| Household settings file (`household.yaml`) | A `household_settings` JSONB row, versioned | `save_household` writes the row; validation unchanged |
| APScheduler inside the API | EventBridge Scheduler every 15 minutes → Lambda runs `tick_all` in batches (SQS fan-out past ~1,000 households) | Already one idempotent `tick` per household with a `sent` table |
| Resend | SES with the agentls.com domain verified (DKIM, SPF, DMARC) | Swap the sender function |
| Flyer and receipt photos (in memory) | Uploaded to S3 by pre-signed URL, read, deleted (1-day lifecycle) | Move the upload to S3 for large photos |
| Models | Bedrock behind the same aliases (`helper-suggest`, `helper-vision`, `helper-notes`) | `config/models.yaml` entries; eval gate before switching (`helper eval --alias helper-candidate`) |
| `HELPER_SECRET` in `.env` | Secrets Manager, rotated yearly with a two-key overlap | Accept the previous key for verification during rotation |
| Logs | CloudWatch (counts and hashes only, as now) | — |
| Push (Expo) | Unchanged | Store push receipts and prune dead tokens on a schedule |

The Terraform starter in `infra/aws/` creates the parts with no running cost until used (buckets with lifecycle
rules and encryption, the scheduler role, a function role scoped to them and to approved Bedrock models). It hasn't
been applied to a live account. Costs depend on traffic and model use; the solver itself runs for free in the API.

## Subscriptions

- **Apple requires In-App Purchase** for a digital subscription unlocked in an iOS app (Guideline 3.1.1). Use
  StoreKit 2 through **RevenueCat** (its React Native SDK works in Expo development builds) or `expo-iap`; RevenueCat
  also handles Android billing, receipts and the paywall.
- **Entitlement lives on the server:** App Store Server Notifications V2 (or RevenueCat webhooks) mark a household
  `active`, `grace` or `lapsed` in the `households.plan` column that already exists. Only the admin's subscription
  counts; invited family members never pay.
- **Lapsed:** read-only (plans and recipes stay viewable, no new drafts) for 30 days, then the admin is asked whether
  to delete or keep.
- **The welcome wizard** gets the paywall at the "Lil'Helper Family" step: free trial, then monthly or yearly. Show
  price, period and renewal terms on the paywall itself, and link to Terms and the Privacy Policy (Guideline 3.1.2).
- **Restore purchases** and **Manage subscription** buttons in Home → Account.

## Privacy and children

- **Privacy policy** at a public URL, linked in the app and in App Store Connect; **App Privacy** answers: email
  (account), user content (recipes, plans), purchases (spending you record) — linked to the user, not used for
  tracking. No third-party ads or analytics SDKs.
- **Children:** parents enter children's first names, ages and allergies. Under COPPA, collecting personal
  information **from** a child under 13 needs verifiable parental consent, so in production kid accounts with their
  own sign-in are limited to 13+ unless a parent consents through the admin's account (the admin attests and is the
  account holder). Children under 13 appear as profiles only. Allergies are health-adjacent: encrypt the household
  settings column with a per-household data key (KMS).
- **Models never see names** (as now), and Bedrock keeps prompts in-region without training on them.
- **Deletion:** account and household deletion are immediate in the database; backups age out in 35 days, and the
  policy says so.
- **Data export:** a "Download my household" JSON in Home → Account (GDPR/CCPA access requests).

## Before submitting to the App Store

- [ ] Hosted service in AWS with RLS, backups, and an uptime check on `/api/health`
- [ ] Subscriptions through RevenueCat, server entitlement, paywall in the wizard, restore and manage buttons
- [ ] Privacy policy and terms pages; App Privacy questions answered; children's handling as above
- [ ] Sign-in links through SES; Universal Links (`https://helper.agentls.com/signin`) so emailed links open the app
      instead of a custom scheme
- [ ] Rate limits moved to the edge (WAF) and to Redis/ElastiCache instead of in-process
- [ ] Load test: 1,000 households' Saturday drafts in the scheduler window
- [ ] Review notes for Apple with a demo account and sign-up code
