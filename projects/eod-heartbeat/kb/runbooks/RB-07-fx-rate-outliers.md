---
id: RB-07
title: FX rate outliers
break_types: [fx_outlier, pnl_break]
hints: [fx]
owner: fund-operations
---

# RB-07 FX rate outliers

## Symptoms
An FX rate moves more than 10% day over day, and P&L for books holding that currency shows a large break.

## Likely causes
- A decimal-place error in the vendor file (for example 11.62 instead of 1.162).
- The rate was quoted inverted (USD per EUR instead of EUR per USD).

## Steps
1. Compare the rate with the previous day and a second FX source.
2. If it is a vendor error, request a corrected file and hold P&L for the affected books.
3. Load the corrected file and rerun only the P&L step for the affected books.
4. Confirm the P&L break clears and note the vendor error in the incident log.

## Escalation
Notify the ops lead if the corrected file is not received before the NAV cutoff.
