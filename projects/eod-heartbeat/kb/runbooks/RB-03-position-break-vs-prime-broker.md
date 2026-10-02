---
id: RB-03
title: Position break versus the prime broker
break_types: [position_break]
hints: [position]
owner: fund-operations
---

# RB-03 Position break versus the prime broker

## Symptoms
Internal positions (opening + trades + adjustments) differ from the prime broker's end-of-day position file for one or more securities.

## Likely causes
- A trade is booked internally but not at the prime broker yet (timing), or the reverse.
- A corporate action (split, merger) was applied by the broker but not internally.
- A trade was duplicated or cancelled in only one system.

## Steps
1. Compare the break quantity with the day's trades for that security; a match to one trade usually means timing or a duplicate.
2. Check the corporate actions file for the security on the business date.
3. Raise a break with the prime broker's middle office if the cause is on their side.
4. Book any internal correction as a position adjustment with a reason, never by editing the trade history.

## Escalation
Escalate unresolved breaks above $1 million market value to the ops lead before NAV sign-off.
