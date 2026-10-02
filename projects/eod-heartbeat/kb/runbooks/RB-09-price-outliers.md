---
id: RB-09
title: Price outliers
break_types: [price_outlier]
hints: [price]
owner: fund-operations
---

# RB-09 Price outliers

## Symptoms
A security's price moves more than 25% in a day with no corporate action recorded.

## Likely causes
- A genuine market move after news.
- A vendor error or a unit change (pence instead of pounds).

## Steps
1. Check news and a second pricing source for the security.
2. If the move is genuine, mark the price as validated in the pricing log.
3. If it is an error, request a corrected price and rerun only the P&L step for the book.

## Escalation
Unvalidated moves on positions above $1 million go to the valuation committee.
