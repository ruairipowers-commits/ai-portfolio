---
id: RB-06
title: Stale prices
break_types: [stale_price]
hints: [stale]
owner: fund-operations
---

# RB-06 Stale prices

## Symptoms
A security's closing price is unchanged for four or more consecutive business days.

## Likely causes
- The security is illiquid and genuinely did not trade.
- The vendor stopped updating the security (delisting, identifier change, entitlement lapse).

## Steps
1. Check the exchange or a second pricing source for the last trade date.
2. If the security traded, request a corrected price from the vendor for each stale date.
3. If it did not trade, record the price as validated stale in the pricing log.
4. For positions above $1 million, ask the valuation committee whether an evaluated price is needed.

## Escalation
Stale prices on more than 1% of NAV go to the valuation committee.
