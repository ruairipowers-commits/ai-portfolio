---
id: RB-11
title: Trade booked after the prime-broker cutoff
break_types: [position_break]
hints: [late_trade, timing]
owner: fund-operations
---

# RB-11 Trade booked after the prime-broker cutoff

## Symptoms
A position break equal to one trade booked after the prime broker's 16:30 cutoff.

## Likely causes
- Late execution or late booking; the prime broker will include the trade in the next day's file.

## Steps
1. Confirm the trade's booked time is after 16:30 and the break quantity equals the trade quantity.
2. Mark the break as a timing difference expected to clear the next business day.
3. Check the next day's prime-broker file; if the break has not cleared, treat it as a real break (RB-03).

## Escalation
No escalation needed for a confirmed timing difference.
