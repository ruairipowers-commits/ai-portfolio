# Dinner Peace & Dinner Peace Pro — Web Application & Chef Suite

This directory contains the production-ready responsive website for **Dinner Peace** and **Dinner Peace Pro**, built around the **Trojan Horse Flywheel strategy** that bridges personal chefs and client households.

---

## Architecture & File Structure

```
website/
├── index.html         # Main web application & landing page (Trojan Horse Flywheel + Family & Chef Pro suites)
├── styles.css         # Calming brand styling, celadon sage palette, and flywheel layout system
├── app.js             # Interactive client-side application logic & state controllers
├── voice-engine.js    # Hands-free kitchen voice recognition & command execution engine
├── CNAME              # Domain mapping to dinnerpeace.app
├── vercel.json        # Production routing & edge configuration for Vercel
├── assets/            # Vector graphics, app icons, and illustrations
│   └── FinalIcon.png  # High-resolution (1024x1024) official icon (Chef Toque Apple + Glass Meal Prep Container)
└── README.md          # Technical documentation & feature overview (this file)
```

---

## The Trojan Horse Flywheel Strategy

The marketing and platform architecture are built on a symbiotic, two-sided distribution flywheel:

```
┌────────────────────────────────────────────────────────┐
│ 1. PERSONAL CHEF (PRO)                                 │
│ Chef adopts Dinner Peace Pro to manage households,    │
│ track allergies, prep meals, and optimize rewards.     │
└───────────────────────────┬────────────────────────────┘
                            │ Onboards client households for free
                            ▼
┌────────────────────────────────────────────────────────┐
│ 2. THE WHITE-GLOVE TROJAN HORSE                        │
│ Family downloads Dinner Peace to access fridge logs,   │
│ numbered glass containers (#1–#6), & reheating temps.  │
└───────────────────────────┬────────────────────────────┘
                            │ Solves the remaining 4–5 nights
                            ▼
┌────────────────────────────────────────────────────────┐
│ 3. 7-DAY HOUSEHOLD EXPANSION                           │
│ On non-chef nights, the family uses Dinner Peace for   │
│ their own meal planning, grocery runs, & pantry meals. │
└───────────────────────────┬────────────────────────────┘
                            │ Word-of-mouth & chef referrals
                            ▼
┌────────────────────────────────────────────────────────┐
│ 4. VIRAL FLYWHEEL                                      │
│ Families recommend their chef; busy families without a │
│ chef discover and hire Dinner Peace Pro culinary pros. │
└────────────────────────────────────────────────────────┘
```

1. **The Chef Enters the Household**:
   * Personal chefs need professional tooling to scale from 3 to 15+ households. They subscribe to **Dinner Peace Pro** ($29–$59/mo).
   * As part of their service, chefs give their clients a white-glove digital experience by inviting them to the free **Dinner Peace** app.
   * Clients see exactly what the chef cooked, container shelf-life, and 1-tap reheating instructions.
2. **Solving the 5-Day Gap**:
   * Personal chefs typically prep for 2 to 3 nights a week. On the other 4 to 5 nights, the family is on their own.
   * Because the family is already using Dinner Peace, they naturally rely on it for the rest of their week: easy weeknight dinners, aisle-sorted grocery shopping for breakfast/lunch staples, and zero-waste pantry cooking.
3. **Zero-CAC Viral Adoption**:
   * Chefs acquire high-LTV families at zero customer acquisition cost for the consumer app.
   * Families recommend their personal chef to neighbors and friends, driving new chef subscriptions and client roster expansion.

---

## 1. Dinner Peace for Families

* **Serene Weekly Planning**: Balanced 7-day meal plans adapted to dietary targets and prep time.
* **Aisle-Sorted Grocery Runs**: Automatically generated, store-sectioned grocery lists.
* **Pantry-First Cooking**: "Cook From What You Have" suggestions to reduce food waste.
* **Allergen & Picky-Eater Safety**: Allergy safeguards and kid-friendly portions.
* **Card Wallet**: Every card's rewards, yearly caps, limits, expiry and delivery credits, with the next best card when a bonus runs out.
* **Delivery Services**: Instacart, Amazon/Whole Foods, DoorDash, Uber Eats, Walmart and Grubhub hand-offs.
* **Find a Chef**: Search personal chefs near your home, ask to meet, hire or switch chefs.
* **Chef Connection (Free)**: Receive meal prep logs, container tracking, and reheating instructions directly from your private chef.

---

## 2. Dinner Peace Pro for Personal Chefs

* **Household Prioritization & Scaling**: Manage multiple households, track prep days, and maximize billable hours.
* **Deep Client Dossiers**: Centralized allergies, favorite family meals, kid dislikes, and preferred grocery brands.
* **Budgets & Cost Tracking**: Grocery spend limits, receipt capture, margins, and client invoices.
* **Fridge & Leftover Management**: Labeled glassware containers (#1–#6), fridge logs, and shelf-life monitoring.
* **Print or Email Reheating Instructions**: Countertop kitchen cards or instant email guides with oven/stovetop temperatures.
* **Cross-Household Shopping & Card Rewards**: Consolidate grocery runs across multiple homes into one route; pay with chef rewards card to earn points and auto-generate client chargebacks (or charge client card on file).
* **Colleague Delegation & Away Plans**: Temporary backup chef access or auto-emailed workflow plans for vacation/sick coverage.
* **Find Families**: Households near you looking for a chef, what they'd pay, and requests to meet.
* **"What Do I Do Next?" Home Dashboard**: Clutter-free home screen showing today's priority kitchen, immediate next prep step, or next store stop.
* **100% Hands-Free Kitchen Voice Control (`voice-engine.js`)**: Dictate notes, fridge logs, or receipts hands-free while cooking.

---

## 3. High-Quality Brand Icon (`assets/FinalIcon.png`)

* **Dimensions**: 1024 × 1024 resolution.
* **Motifs**: Soft Celadon Sage squircle background (`#BFCCBA`), Kraft Grocery Bag (`#C49E6A`), Apple wearing white Chef Toque (`#FAF7F0` / `#D06253`), Glass Meal Prep Container with lock-lid (`#B8D3DC`), Steaming Olive Soup Bowl (`#94946E`), Golden Toasted Sandwich (`#F0BF6A`), and Sleeping Silver Spoon (`#B8BFC4`).
