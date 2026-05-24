#!/usr/bin/env python3
"""
Seed Qdrant with 60 synthetic historical disruption records + 60 matching responses.
Idempotent — uses deterministic UUIDs so re-runs don't create duplicates.

Week 3 update: richer description narratives (2-3 sentences) and structured
per-action response lists for better semantic retrieval quality.

Usage:
    python scripts/seed_qdrant.py
"""

import sys
import os
import uuid
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from qdrant_client.models import PointStruct

from src.memory.qdrant_client import get_qdrant_client, setup_collections, get_embedding
from src.config.settings import get_settings

console = Console()

DISRUPTION_TYPES = ["weather", "port", "tariff", "demand", "geopolitical"]
REGIONS = [
    "Asia-Pacific", "Europe", "North America",
    "Middle East", "Latin America", "Africa",
]

# 2 disruptions per type × region combination = 60 total
# Week 3: richer 2-3 sentence narratives for better semantic retrieval
DISRUPTION_TEMPLATES = {
    "weather": [
        ("Severe monsoon flooding disrupted inland freight corridors in {region}, forcing rerouting of over 3,000 containers. "
         "River barge capacity dropped 60% and road networks remained impassable for {days} days, "
         "causing cascading inventory shortages across downstream manufacturers."),
        ("A Category 4 typhoon made landfall near the primary port cluster in {region} in {year}, halting all terminal operations for 11 days. "
         "Over 200 vessels were rerouted to secondary ports, overwhelming their capacity and triggering port congestion surcharges. "
         "Severity {severity}/10 event with estimated $1.8B in cargo delays."),
        ("Extended drought in {region} reduced river barge capacity by 70% across major inland waterways, disrupting coal and grain flows. "
         "Rail and road alternatives operated at 140% of normal utilisation, driving spot freight rates up 85%. "
         "Supply chain impacts lasted {days} days before water levels recovered."),
        ("Record snowfall closed mountain passes and key rail lines in {region} for 12 consecutive days in {year}. "
         "Automotive and electronics manufacturers in the region faced component shortages as inbound shipments were delayed. "
         "Severity {severity}/10 — road closures extended to secondary routes on day 4."),
        ("Extreme wildfire smoke triggered air cargo ground stops at three major airports in {region} in {year}. "
         "Time-sensitive pharmaceutical and semiconductor shipments were grounded for 48-72 hours, "
         "forcing emergency ocean freight reroutings that added 8-12 days of lead time."),
        ("An extreme heat event buckled rail tracks across {region}, forcing freight rerouting to road networks already operating at capacity. "
         "Consumer electronics and FMCG supply chains experienced {days}-day delays as {severity}/10 severity heat wave persisted. "
         "Cooling infrastructure at several warehouses failed, resulting in spoilage of temperature-sensitive cargo."),
    ],
    "port": [
        ("Dock workers union strike at the largest container terminal in {region} entered its second week in {year}, reducing port throughput by 45%. "
         "Over 120 vessels diverted to alternative ports, but congestion quickly built at secondary terminals. "
         "Severity {severity}/10 — estimated {days}-day resolution based on historical labour disputes."),
        ("A major IT system failure at the primary {region} port caused a 96-hour container tracking outage, paralysing customs clearance. "
         "Importers were unable to retrieve cargo, and 40,000 TEUs accumulated in the terminal yard. "
         "Severity {severity}/10 — cascading effects on just-in-time manufacturers lasted {days} days."),
        ("A new customs inspection mandate in {region} tripled the average container clearance time from 3 to 9 days starting {year}. "
         "Port dwell time surged from 4 to 11 days, triggering demurrage charges averaging $8,000 per container. "
         "Supply chains dependent on predictable lead times faced {severity}/10 severity disruption lasting {days} days."),
        ("A container ship grounding in the main {region} channel blocked port access for 78 hours in {year}. "
         "Over 85 vessels were held at anchorage, accumulating demurrage costs and delaying time-sensitive cargo. "
         "Severity {severity}/10 disruption with {days}-day knock-on effects on port scheduling."),
        ("Terminal fire at the primary {region} hub port destroyed three berths and damaged container handling equipment in {year}. "
         "Port capacity was reduced by 35% for an extended period, with reconstruction estimated at 18 months. "
         "Severity {severity}/10 — {days}-day full normalisation expected as alternative terminals absorb diverted volume."),
        ("Severe congestion surge at major {region} ports pushed vessel waiting times to 14 days at anchorage in {year}. "
         "Container equipment imbalance compounded delays as empty boxes accumulated at inland depots. "
         "Severity {severity}/10 — exporters and importers faced {days}-day disruption with spot rates up 120%."),
    ],
    "tariff": [
        ("An emergency 35% tariff was imposed on semiconductor imports into {region} effective {year}, triggering a supply chain shock. "
         "Electronics manufacturers immediately accelerated Q4 purchasing to beat the tariff, exhausting available ocean freight capacity. "
         "Severity {severity}/10 — {days}-day stabilisation period as supply chains adjusted to the new cost structure."),
        ("The {region} trading bloc announced retaliatory tariffs of 25% on agricultural and consumer goods from a rival trading partner in {year}. "
         "Importers scrambled to front-load shipments, overwhelming port capacity in a 3-week pre-tariff surge. "
         "Severity {severity}/10 — post-surge inventory correction lasted {days} days."),
        ("A new carbon border adjustment mechanism took effect in {region} in {year}, increasing import costs by 15% for high-emission goods. "
         "Suppliers across Asia and Latin America were unprepared for compliance documentation requirements, causing customs delays. "
         "Severity {severity}/10 — {days}-day normalisation as trade compliance processes were updated."),
        ("Anti-dumping duties of 28% were placed on steel imports from {region} in {year}, affecting downstream automotive and construction industries. "
         "Domestic steel prices increased 18% within 30 days as importers absorbed the cost shock. "
         "Severity {severity}/10 — {days}-day supply chain adjustment period as alternative sourcing was established."),
        ("A sudden tariff renegotiation collapsed a major trade agreement between {region} and a key trading partner in {year}, effective in 60 days. "
         "Supply chain planners had limited time to restructure sourcing before duties reverted to WTO rates. "
         "Severity {severity}/10 — {days}-day disruption with long-tail effects on sourcing strategy."),
        ("Export controls on rare earth materials from {region} were announced without warning in {year}, triggering a global component shortage. "
         "Electronics and EV manufacturers scrambled to secure alternative material sources within 45 days. "
         "Severity {severity}/10 — estimated {days}-day resolution as alternative supply chains were qualified."),
    ],
    "demand": [
        ("A post-pandemic restocking wave in {region} drove a 280% surge in container bookings in {year}, overwhelming available vessel capacity. "
         "Spot freight rates on key trade lanes reached $18,000 per 40ft container — a 6× increase over pre-pandemic levels. "
         "Severity {severity}/10 — {days}-day normalisation as new vessel capacity entered the market."),
        ("A major retail platform in {region} launched same-day delivery infrastructure in {year}, exhausting all available air freight capacity. "
         "Express shipment lead times stretched from 2 days to 8-12 days as capacity was reallocated to the new service. "
         "Severity {severity}/10 — {days} days before market capacity adjusted."),
        ("Seasonal holiday demand spike in {region} outpaced available ocean freight capacity by 3× in {year}, with severity {severity}/10. "
         "Retailers who had not pre-booked vessel space 90 days in advance were unable to secure capacity at any price. "
         "Stockout rates for seasonal goods reached 24% — three times the annual average."),
        ("An infrastructure stimulus package in {region} triggered an explosion in steel, cement, and heavy equipment demand in {year}. "
         "Port congestion at major {region} terminals reached severity {severity}/10 as bulk cargo overwhelmed terminal capacity. "
         "Commodity supply chains took {days} days to rebalance as additional vessel supply was deployed."),
        ("An EV battery supply crunch in {region} caused widespread automotive plant shutdowns in {year}, cascading across {severity}/10 severity. "
         "Lithium and cobalt component shortages forced 12 OEM plants to halt or reduce production for {days} days. "
         "Tier-2 and tier-3 supplier disruptions compounded the primary shortage."),
        ("Commodity price speculation in {region} drove panic buying of industrial raw materials in {year}, creating artificial scarcity. "
         "Container demand for bulk dry goods surged 180% in 3 weeks, filling all available spot capacity. "
         "Severity {severity}/10 — normalisation took {days} days as speculative inventory unwound."),
    ],
    "geopolitical": [
        ("Trade sanctions imposed on {region} blocked access to the SWIFT payment system for major exporters in {year}. "
         "Cross-border freight payments were disrupted, and shipping lines suspended services within 72 hours. "
         "Severity {severity}/10 — {days}-day full impact period before alternative payment infrastructure was established."),
        ("A territorial dispute escalated in {region} in {year}, forcing commercial vessels to take a 4,200 km detour around the contested strait. "
         "Transit times on affected trade lanes increased by 12-18 days, and insurance war-risk premiums rose 380%. "
         "Severity {severity}/10 — {days}-day disruption as carriers assessed security and rerouting options."),
        ("A coup in {region} closed all land and sea borders for 3 weeks in {year}, stranding $2.1B in perishable cargo. "
         "Severity {severity}/10 — regional supply chains were effectively severed, with no alternative routing available. "
         "Post-conflict stabilisation required {days} days before freight flows partially resumed."),
        ("A state-sponsored cyber attack on {region} customs clearance systems paralysed cross-border freight for 8 days in {year}. "
         "Severity {severity}/10 — 45,000 import declarations were frozen, halting manufacturing inputs across the region. "
         "Physical paper fallback procedures extended clearance times from 1 day to 9-14 days for {days} total."),
        ("A naval blockade in the {region} strait diverted 18% of global LNG shipments and disrupted container routes in {year}. "
         "Energy price spikes drove freight cost increases as carriers absorbed higher fuel costs on alternative routes. "
         "Severity {severity}/10 — {days}-day disruption before diplomatic resolution permitted partial passage."),
        ("An export ban on critical minerals from {region} was enacted overnight in {year}, triggering a supply chain emergency across tech and EV sectors. "
         "Severity {severity}/10 — manufacturers with no alternative sources faced immediate production curtailments. "
         "Alternative mineral supply qualification required {days} days and significant premium costs."),
    ],
}

# Week 3: structured lists of 3-5 specific, actionable response actions
RESPONSE_ACTIONS = {
    "weather": [
        [
            "Activated alternative overland routing bypassing flood zones within 24 hours",
            "Pre-positioned emergency inventory at 5 inland distribution centres before storm landfall",
            "Negotiated 3,000 CBM of spot air freight capacity on 12 daily flights",
            "Issued force majeure notifications to 28 tier-1 customers with revised ETA",
        ],
        [
            "Chartered 4 coastal vessels to bypass closed river barge network",
            "Coordinated with 6 road carriers to establish convoy routing through unaffected corridors",
            "Expedited clearance of critical healthcare and food cargo through emergency customs lanes",
            "Activated backup cross-dock facility 180 km from primary distribution centre",
        ],
        [
            "Diverted 2,400 TEUs to rail corridor unaffected by weather event",
            "Partnered with local emergency management agency to prioritise freight access",
            "Extended payment terms for affected suppliers to preserve cash flow",
            "Deployed drone delivery for last-mile in inaccessible flood zones",
        ],
    ],
    "port": [
        [
            "Diverted all inbound vessels to secondary port 340 km away within 48 hours",
            "Arranged dedicated inland truck bridge connecting secondary port to primary distribution network",
            "Deployed emergency pop-up warehouse facility adjacent to alternate terminal",
            "Negotiated priority berthing slots at secondary port for critical cargo",
            "Issued customer notifications with revised lead times within 12 hours of disruption",
        ],
        [
            "Engaged premium freight forwarder to expedite customs via alternative electronic system",
            "Activated pre-positioned safety stock covering 14 days of demand for top-50 SKUs",
            "Coordinated with port authority to prioritise perishable and high-value cargo clearance",
            "Air-freighted critical pharmaceutical and semiconductor components to bypass port backlog",
        ],
        [
            "Rerouted Trans-Pacific shipments via secondary port with 6-day transit extension",
            "Negotiated demurrage waivers with 3 major shipping lines covering held cargo",
            "Activated supplier emergency production protocol for 8 critical assemblies",
            "Established dedicated tracking dashboard for all delayed shipments",
            "Briefed board of directors within 6 hours with financial impact assessment",
        ],
    ],
    "tariff": [
        [
            "Accelerated import timeline for 180 SKUs to clear customs before tariff effective date",
            "Stockpiled 90-day safety buffer of affected components at bonded warehouse",
            "Initiated supplier qualification process across 3 tariff-exempt origin countries",
            "Filed tariff exclusion requests for 24 product categories within 48 hours",
            "Restructured bill of materials for 6 products to reduce tariff exposure by 40%",
        ],
        [
            "Established duty drawback programme recovering $2.3M in overpaid import duties",
            "Sourced 35% of tariff-affected volume from duty-free zone alternative suppliers",
            "Negotiated cost-sharing arrangement with top-5 customers on tariff surcharge",
            "Implemented country-of-origin diversification across 3 new source markets",
        ],
        [
            "Deployed trade compliance task force to update all import documentation",
            "Onboarded 4 alternative suppliers in tariff-exempt countries within 45 days",
            "Implemented tariff engineering on 12 product classifications to reduce duty rate",
            "Established weekly tariff monitoring cadence with customs broker",
        ],
    ],
    "demand": [
        [
            "Chartered 3 dedicated vessels to secure guaranteed capacity for peak season",
            "Secured block space agreements with top-4 carriers covering 85% of forecast volume",
            "Implemented dynamic safety stock algorithm adjusting daily to demand signals",
            "Shifted 20% of volume to air freight for highest-margin products",
            "Negotiated premium booking window extensions with 6 logistics providers",
        ],
        [
            "Activated nearshore fulfilment from Mexico facility to reduce lead time from 45 to 8 days",
            "Implemented demand rationing protocol allocating available stock to tier-1 accounts first",
            "Onboarded 2 new 3PL partners to expand warehousing capacity by 40%",
            "Deployed demand sensing model updating replenishment signals every 6 hours",
        ],
        [
            "Pre-positioned inventory at 8 regional distribution centres 60 days before peak",
            "Implemented customer allocation framework to prevent channel over-ordering",
            "Negotiated spot capacity on 4 additional vessels for the peak period",
            "Activated emergency production schedule at supplier for 3 critical SKUs",
        ],
    ],
    "geopolitical": [
        [
            "Activated dual-sourcing protocol switching 60% of volume to sanctioned-region-free suppliers",
            "Onboarded 3 alternative suppliers in neutral countries within 30 days",
            "Rerouted payment flows through SWIFT-connected banking partners in 3rd countries",
            "Engaged trade compliance and sanctions legal team within 4 hours of announcement",
            "Established daily monitoring of regulatory updates with external counsel",
        ],
        [
            "Rerouted all affected vessels via Cape of Good Hope alternative — 14-day transit extension",
            "Absorbed lead time increase into safety stock buffer pre-positioned 30 days prior",
            "Negotiated war-risk insurance premium caps with underwriters for 90-day period",
            "Issued force majeure notifications and revised customer delivery commitments",
        ],
        [
            "Established alternative supplier network in 3 unaffected regions within 45 days",
            "Activated commodity hedging strategy to manage raw material cost volatility",
            "Engaged government export credit agency for trade finance support",
            "Implemented enhanced supply chain visibility monitoring with weekly executive briefings",
            "Participated in industry coalition advocating for trade route re-opening",
        ],
    ],
}

OUTCOMES = ["successful", "partial", "failed"]
OUTCOME_WEIGHTS = [0.55, 0.35, 0.10]


def deterministic_uuid(seed: str) -> str:
    """Generate a deterministic UUID from a seed string for idempotency."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"scdf.seed.{seed}"))


def build_disruption_text(dtype: str, region: str, severity: int, year: int, resolution_days: int) -> str:
    """Build a rich 2-3 sentence disruption narrative."""
    template = random.choice(DISRUPTION_TEMPLATES[dtype])
    return template.format(region=region, severity=severity, year=year, days=resolution_days)


def build_response_text(dtype: str, region: str, actions: list[str], outcome: str, days: int) -> str:
    """Build embedding text for the response record."""
    actions_str = "; ".join(actions[:3])
    return (
        f"Response to {dtype} supply chain disruption in {region}. "
        f"Actions taken: {actions_str}. "
        f"Outcome: {outcome}. Resolved in {days} days."
    )


def main():
    console.rule("[bold blue]SCDF Qdrant Seed Script[/bold blue]")

    settings = get_settings()
    client = get_qdrant_client()

    console.print("[cyan]Setting up collections...[/cyan]")
    setup_collections(client)

    disruption_points: list[PointStruct] = []
    response_points: list[PointStruct] = []

    # Build all records: 2 per (type × region) = 5 types × 6 regions × 2 = 60
    records: list[dict] = []
    for dtype in DISRUPTION_TYPES:
        for region in REGIONS:
            for variant in range(2):
                severity = random.randint(3, 10)
                year = random.randint(2018, 2024)
                resolution_days = random.randint(3, 90)
                seed_key = f"{dtype}-{region}-{variant}"
                disruption_id = deterministic_uuid(seed_key)

                description = build_disruption_text(dtype, region, severity, year, resolution_days)
                records.append(
                    {
                        "disruption_id": disruption_id,
                        "disruption_type": dtype,
                        "region": region,
                        "severity": severity,
                        "year": year,
                        "resolution_days": resolution_days,
                        "resolved": True,
                        "description": description,
                        "seed_key": seed_key,
                    }
                )

    random.shuffle(records)

    total_ops = len(records) * 2  # disruption embed + response embed
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Embedding and upserting records...", total=total_ops)

        for rec in records:
            # ── Disruption record ────────────────────────────────────────────
            d_vec = get_embedding(rec["description"])
            disruption_points.append(
                PointStruct(
                    id=deterministic_uuid(f"d-{rec['seed_key']}"),
                    vector=d_vec,
                    payload={
                        "disruption_id": rec["disruption_id"],
                        "disruption_type": rec["disruption_type"],
                        "region": rec["region"],
                        "severity": rec["severity"],
                        "year": rec["year"],
                        "resolution_days": rec["resolution_days"],
                        "resolved": rec["resolved"],
                        "description": rec["description"],
                    },
                )
            )
            progress.advance(task)

            # ── Response record ──────────────────────────────────────────────
            response_id = deterministic_uuid(f"r-{rec['seed_key']}")
            outcome = random.choices(OUTCOMES, weights=OUTCOME_WEIGHTS, k=1)[0]
            actual_days = int(rec["resolution_days"] * random.uniform(0.8, 1.4))
            # Week 3: pick a structured list of 3-5 actions
            actions_list = random.choice(RESPONSE_ACTIONS[rec["disruption_type"]])
            cost_k = round(random.uniform(50, 5000), 1)

            response_text = build_response_text(
                rec["disruption_type"], rec["region"], actions_list, outcome, actual_days
            )
            r_vec = get_embedding(response_text)

            response_points.append(
                PointStruct(
                    id=deterministic_uuid(f"rp-{rec['seed_key']}"),
                    vector=r_vec,
                    payload={
                        "response_id": response_id,
                        "disruption_id": rec["disruption_id"],
                        # Store as JSON-encoded list for structured retrieval
                        "actions_taken": actions_list,
                        "outcome": outcome,
                        "resolution_days": actual_days,
                        "cost_usd_k": cost_k,
                        "description": response_text,
                    },
                )
            )
            progress.advance(task)

    # ── Batch upsert ─────────────────────────────────────────────────────────
    console.print("[cyan]Upserting disruption records...[/cyan]")
    client.upsert(
        collection_name=settings.qdrant_collection_disruptions,
        points=disruption_points,
    )

    console.print("[cyan]Upserting response records...[/cyan]")
    client.upsert(
        collection_name=settings.qdrant_collection_responses,
        points=response_points,
    )

    # ── Verify counts ────────────────────────────────────────────────────────
    d_count = client.count(settings.qdrant_collection_disruptions).count
    r_count = client.count(settings.qdrant_collection_responses).count

    console.print()
    console.print(f"[green]✓ Disruptions collection: {d_count} records[/green]")
    console.print(f"[green]✓ Responses collection:   {r_count} records[/green]")
    console.print()
    console.rule("[bold green]Seed complete[/bold green]")


if __name__ == "__main__":
    main()
