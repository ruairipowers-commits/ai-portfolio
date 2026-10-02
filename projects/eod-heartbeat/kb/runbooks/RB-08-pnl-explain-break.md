---
id: RB-08
title: P&L explain break
break_types: [pnl_break]
hints: [pnl]
owner: fund-operations
---

# RB-08 P&L explain break

## Symptoms
Computed P&L for a book (prior positions x price change x FX) differs from the risk system's reported P&L by more than $25,000.

## Likely causes
- A bad input: a wrong price, FX rate or position for one security.
- A corporate action or trade not reflected in one of the two systems.
- The risk system ran before a late file arrived.

## Steps
1. Break the difference down by security to find the one or two names driving it.
2. Check those names for price, FX, position or corporate action breaks on the same date.
3. Fix the input using the runbook for that break type, then rerun only the P&L step.
4. If no input is wrong, ask the risk team whether their run used different data.

## Escalation
Unexplained P&L breaks above $250,000 go to the ops lead and the CFO's office before NAV sign-off.
