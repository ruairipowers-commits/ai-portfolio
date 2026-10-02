---
id: RB-04
title: Corporate action not applied internally
break_types: [position_break, pnl_break]
hints: [corporate_action, split]
owner: fund-operations
---

# RB-04 Corporate action not applied internally

## Symptoms
After a split or other corporate action, the prime broker shows the adjusted quantity but internal positions show the old quantity. P&L shows a large loss or gain on the security because the price adjusted but the quantity did not.

## Likely causes
- The corporate action was announced late and the internal security master was not updated before the EOD run.
- The corporate actions feed delivered the event but the internal booking step failed.

## Steps
1. Confirm the event in the corporate actions file: ticker, action type and ratio.
2. Check that the break quantity equals the old quantity times (ratio - 1).
3. Book a position adjustment for the ratio with the reason "corporate action" and the event reference.
4. Rerun only the P&L step for the affected book after the adjustment, and confirm the P&L break clears.

## Escalation
Tell the NAV team the P&L for the book is restated for the date.
