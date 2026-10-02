# Escalation integrations

The console escalates a governance issue in three steps. It opens an **incident**, switches the workflow off if
the issue is serious enough, and **notifies** people. Email is built. Ticketing systems are a designed option that
isn't wired up yet. This page covers how each fits, and what building the ticket channels would take.

```
issue ─▶ incident INC-nnnn ─┬─▶ kill switch off (auto-shutdown level)
                            └─▶ notify (notify level) ─┬─ email (SMTP)                    built
                                                       ├─ PagerDuty Events API v2         design below
                                                       └─ ServiceNow incident (Table API)  design below
```

Every notification is written to the console's **outbox** (`notifications` table) before delivery and updated
with the result. That gives an audit trail of who was told what and when (OBS-01). It also means the flow works,
and can be demonstrated, with no mail server at all.

## Email (built)

| Setting | Where |
|---|---|
| SMTP server and login | env `SMTP_HOST`, `SMTP_PORT` (587 STARTTLS / 465 TLS), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` |
| Default recipient(s) | env `GOVERNANCE_ALERT_EMAIL` (comma-separated), always copied |
| Per-workflow recipients, notify level, auto-shutdown level, rules | console **Settings** page (admin) |
| Link base in emails | env `GOVERNANCE_PUBLIC_URL`, else the deployed console URL, else the request URL |
| Daily cap | `config/escalation.yaml` → `limits.emails_per_day` |

With Gmail, `SMTP_PASSWORD` is an [app password](https://support.google.com/accounts/answer/185833). The account
needs 2-Step Verification. For a firm, send through its relay or a transactional provider (SES, Postmark) from a
domain with SPF, DKIM and DMARC records.

The email carries:

- severity, workflow, control ID and owner;
- who triggered it, the run ID and the guardrail signals;
- whether the workflow was switched off;
- the rule's guidance;
- a button to the incident page, plus a link to the workflow itself.

It never includes prompts, documents or answers, because the console never receives them (NFR-5).

## Ticketing: PagerDuty and ServiceNow (design; not built)

Both are listed as channels in `config/escalation.yaml` with `implemented: false`, and appear on the Settings
page as integration options. Each incident page already shows the exact payload the console would send.
`notify.ticket_payload()` builds that payload and is covered by tests, so the field mapping can be reviewed
before anything is connected.

| | PagerDuty | ServiceNow |
|---|---|---|
| API | Events API v2: `POST https://events.pagerduty.com/v2/enqueue` | Table API: `POST https://<instance>.service-now.com/api/now/table/incident` |
| Auth | integration routing key (`PAGERDUTY_ROUTING_KEY`) | OAuth client credentials or a basic-auth integration user (`SERVICENOW_*`) |
| One ticket per incident | `dedup_key` = incident ID | `correlation_id` = incident ID |
| Severity | low→info, medium→warning, high→error, critical→critical | impact and urgency 3 / 2 / 1 / 1 |
| Repeats | the same `dedup_key` is re-sent (updates, doesn't re-page) | add a work note to the existing ticket |
| On resolve | `event_action: resolve` with the same `dedup_key` | set `state` = Resolved, with close notes = root cause + fix |
| Link back | `links[]` → the incident page | in `description` |

### Building it

1. Add `send_ticket(channel, payload)` to `notify.py`: an HTTP POST with a short timeout. Run it in the
   background like email, and record the result on the outbox row (`channel` = `pagerduty` / `servicenow`).
2. In `escalation._notify`, call it for each channel with `enabled: true`. Store the returned ticket ID (the
   ServiceNow `sys_id`, or the PagerDuty dedup key) on the incident so resolution can close it.
3. In `escalation.resolve`, send the resolve event or update for each ticket.
4. Secrets go in the environment or a secrets manager (Secrets Manager on AWS), never in the YAML.
5. Retries: three attempts with backoff, then the row stays `failed`. The email channel still runs, so one dead
   channel doesn't silence the alert.

### Which to choose

- **PagerDuty** suits issues that need someone *now*: a high-risk workflow switched off during market hours, or
  an entitlement leak.
- **ServiceNow** suits issues that need a tracked record and a change process: budget overruns, eval failures,
  shadow AI. Many firms already route model-risk findings there.
- A common split is critical and high → PagerDuty, everything → ServiceNow. That is a per-channel
  `notify_at`, a small extension of the per-workflow settings.

### Other options

Slack or Microsoft Teams incoming webhooks have the same shape: a payload builder plus a POST. Jira suits teams
that track model-risk work as issues. If the firm already runs Datadog or Grafana, emit the incident as an event
there and let their existing alert routing take over.
