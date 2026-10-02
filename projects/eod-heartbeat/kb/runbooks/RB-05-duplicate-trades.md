---
id: RB-05
title: Duplicate trades in the OMS extract
break_types: [duplicate_trade, position_break]
hints: [duplicate]
owner: fund-operations
---

# RB-05 Duplicate trades in the OMS extract

## Symptoms
The same trade ID appears more than once in the OMS end-of-day extract, and internal positions exceed the prime broker by the trade quantity.

## Likely causes
- The OMS extract job retried after a timeout and appended the same rows twice.
- A trade was amended and the old version was not removed from the extract.

## Steps
1. List the duplicated trade IDs for the date and confirm they are identical rows.
2. Confirm with the trading desk that only one trade was executed.
3. Book a cancelling position adjustment for the duplicate quantity with reason "duplicate OMS row".
4. Open a ticket with the OMS support team to fix the extract job.

## Escalation
If the duplicate affects client reporting, notify the ops lead.
