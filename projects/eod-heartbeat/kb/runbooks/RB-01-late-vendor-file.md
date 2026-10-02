---
id: RB-01
title: Late vendor or prime-broker file
break_types: [late_file]
hints: [late]
owner: fund-operations
---

# RB-01 Late vendor or prime-broker file

## Symptoms
A feed arrives after its SLA time in `config/feeds`. Downstream steps that depend on it wait, and NAV sign-off moves later.

## Likely causes
- The vendor's own batch ran late; check the vendor status page or the delivery confirmation email.
- The file landed but in the wrong folder or with the wrong name, so the watcher didn't see it.
- Our SFTP pull job failed and retried on its next schedule.

## Steps
1. Confirm whether the file has now arrived: check the landing folder and the arrivals log for the business date.
2. If it has arrived, let the next scheduled heartbeat run pick it up; do not start a manual full rerun.
3. If it has not arrived 30 minutes after SLA, contact the vendor support desk and record the ticket number in the incident.
4. Post the expected arrival time in the ops channel so the NAV team can plan sign-off.

## Escalation
Escalate to the ops lead if a critical feed is more than 60 minutes late or NAV sign-off is at risk.
