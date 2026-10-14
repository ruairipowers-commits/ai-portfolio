---
date: 2026-10-14
slug: supermarket-fridge-cyberattack
short: "Hacked supermarket fridges"
categories: [Security, Operations, AI governance]
tags: [cybersecurity, operational technology, iot, third-party risk, refrigeration, danfoss, cold chain, asset inventory, retail]
audience: [Executives and boards, CTOs and heads of technology, "Risk, compliance and legal", Operations leads]
section: AI insight
---

# The supermarket fridge hack is a lesson about equipment nobody watches

On 11 October, attackers remotely switched supermarket fridges and freezers across France into continuous defrost at
50°C, spoiling stock in hundreds of stores. There's no AI in this story. I'm writing about it because the weakness
it exposed, old internet-connected control equipment from a third-party vendor, is common across industries,
including the ones adopting AI fastest.

<!-- more -->

## What happened

As [Tom's Hardware](https://www.tomshardware.com/tech-industry/cyber-security/unprecedented-cyberattack-cripples-supermarket-fridges-across-europe-as-hackers-activate-automatic-defrosting-delivery-and-store-prices-also-impacted-by-incident)
reported, attackers forced refrigeration units into their defrost cycle, normally about two hours a day, and kept
them there, with temperatures set as high as 50°C. Coopérative U's leader, Dominique Schelcher, confirmed the attack
on X and called it extremely serious.

[Infosecurity Magazine](https://infosecurity-magazine.com/news/french-supermarket-chains) gathered the scale from the
companies:

- Groupement Mousquetaires reported 150 Intermarché and 30 Netto stores affected.
- Carrefour said 80 of its 6,000 stores were primarily affected.
- Groupe Casino said 5% of its Monoprix supermarkets were hit.
- One Intermarché and one Super U in Haguenau alone lost €270,000 of stock, according to BFMTV.

The systems were Danfoss refrigeration controls: BFMTV reported that Danfoss administered them, and an Intermarché
spokesperson confirmed it. The reported
way in was outdated Danfoss control software on consoles that could be operated remotely without a properly secured
connection. That's reported, not yet confirmed by an investigation. Danfoss said the affected models were either
obsolete (the AK-SM800 and AK-SC355) or hadn't been updated (the AK-SM800A), and that it had long advised customers to
keep them current.

Researchers had warned about this. In August 2026, Claroty showed at DEF CON that a compromised controller of this
type could switch off cooling while reporting normal temperatures, and its CTO called refrigeration controllers an
overlooked target. That's a different attack from this one, which was loud and visible.

Exposure was already measurable, too. A Shodan scan on 19 August, a search of devices reachable from the public
internet, found 3,726 of these controllers exposed.

In the Netherlands, Albert Heijn, Etos and Gall & Gall had websites go down, deliveries disrupted, electronic shelf
labels compromised and loyalty programmes suspended. Belgium's Delhaize also reported problems. It isn't clear
whether the Dutch and French incidents are connected, and who was behind either is unknown at the time of writing.
The Paris prosecutor has opened an investigation.

## Why it matters beyond retail

The pattern I'd take from this, as my own reading rather than anything the reporting establishes about these
retailers, is a familiar one. A third-party device controls something physical. It's connected to the internet so the
vendor can manage it remotely. It's past its supported life. And I suspect devices like this are often looked after by
facilities teams or contractors rather than by the people who run IT security.

Every sector has them:

- **Data centres:** cooling and power management.
- **Pharmaceuticals and hospitals:** cold storage for medicines and samples.
- **Logistics:** refrigerated warehouses.
- **Manufacturing:** line controllers and environmental systems.
- **Offices:** building management and access control.

Take an investment firm as a hypothetical. Its risk team will have reviewed its trading systems in detail. But who
owns the cooling in the server room it rents? Which portfolio companies run cold-chain logistics, and do their boards
know which controllers can be reached from the internet? The 11 October attack was obvious almost at once. The quieter
version Claroty demonstrated, cooling off while the readings look normal, would not be.

## What I'd watch out for

These are the controls I'd check first. Most map to [the governance standard](governance.md) under asset inventory,
third-party risk and monitoring:

1. **Inventory includes operational technology.** If a device can change something physical, it's in the register,
   with an owner, a vendor and an end-of-life date.
2. **Nothing is reachable from the internet by default.** Vendor remote access goes through a controlled, logged
   route, not an exposed console.
3. **End-of-life means replacement, not "still working".** Two of the affected models were obsolete. I'd guess that
   replacing them was a cost someone chose to defer, though the reporting doesn't say.
4. **Monitoring doesn't rely only on the device being monitored.** Claroty showed a controller can be made to report
   normal readings. An independent sensor that reports separately, such as a standalone temperature logger alerting over its own
   network, is the defence against that quieter attack.
5. **Incident response covers physical operations.** Containment here meant protecting food, not only systems.

## What I'd try next

I'd start with a simple exercise, which needs no special tools:

1. **List every device that controls something physical:** cooling, power, access, building systems, production
   lines. Facilities and finance (from maintenance contracts) usually know more than IT.
2. **For each one, record** who installed it, which vendor supports it, who can reach it remotely and when it stops
   getting updates. Check the vendor's end-of-life list against the model numbers, the way Danfoss's obsolete AK-SM800
   and AK-SC355 would have shown up.
3. **Look from the outside.** Search for your own addresses on an internet-scanning service such as Shodan, the same
   kind of scan that found 3,726 exposed controllers on 19 August.
4. **Give the results an owner** in risk or security, with a date to fix each exposure.

In my view, the first run of that exercise is one of the most useful things a risk team can do this quarter.

What would change my mind about the lesson: if investigators find the attackers came in through the retailers' own IT
networks rather than exposed controllers. That would make this an IT story with a physical ending. The reporting so
far points to the controllers.

*Drafted with AI agents from a topic my scout found, then edited and approved by me.*
