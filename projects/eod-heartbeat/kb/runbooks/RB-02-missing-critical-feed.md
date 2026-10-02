---
id: RB-02
title: Missing critical feed (no file by cutoff)
break_types: [missing_file, pnl_unavailable]
hints: [missing, fx]
owner: fund-operations
---

# RB-02 Missing critical feed (no file by cutoff)

## Symptoms
A critical feed (FX, prices, trades or prime-broker positions) has not arrived after its SLA. P&L or positions for the affected books cannot be computed, and NAV sign-off is blocked.

## Likely causes
- The vendor did not publish for the date (holiday calendar mismatch, outage).
- Credentials for the vendor endpoint expired, so the pull returned nothing.
- The file was published under a new name or format and was rejected by the loader.

## Steps
1. Check the arrivals log and the pull job's last run for the business date.
2. Ask the vendor desk whether the file was published; if published, request a resend.
3. If the FX file is missing and the vendor confirms an outage, use the approved secondary FX source for the date and record the substitution.
4. Do not carry forward the previous day's file as a substitute without ops lead approval.

## Escalation
Missing critical feeds block NAV: notify the ops lead and the NAV team immediately.
