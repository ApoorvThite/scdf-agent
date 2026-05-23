#!/usr/bin/env python3
"""
Seed Qdrant with 60 synthetic historical disruption records + 60 matching responses.
Idempotent — uses deterministic UUIDs so re-runs don't create duplicates.

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
DISRUPTION_TEMPLATES = {
    "weather": [
        "Severe monsoon flooding disrupted inland freight corridors in {region}.",
        "Category 5 typhoon made landfall near major port cluster in {region}, halting operations.",
        "Extended drought reduced river barge capacity by 70% across {region} waterways.",
        "Record snowfall closed mountain passes and rail lines in {region} for 12 days.",
        "Wildfire smoke forced air cargo ground stops at three major airports in {region}.",
        "Extreme heat buckled rail tracks in {region}; freight rerouted to road.",
    ],
    "port": [
        "Dock workers union strike at the largest container terminal in {region} entered week two.",
        "IT system failure at major {region} port caused 96-hour container tracking outage.",
        "New customs inspection mandate in {region} tripled average clearance time to 9 days.",
        "Container ship grounding in {region} channel blocked access for 78 hours.",
        "Terminal fire at {region} hub destroyed three berths; 18-month reconstruction expected.",
        "Congestion surge in {region} pushed vessel waiting times to 14 days.",
    ],
    "tariff": [
        "Emergency 35% tariff imposed on semiconductor imports into {region}.",
        "{region} bloc announced retaliatory tariffs on agricultural goods from rival trading partner.",
        "New carbon border adjustment mechanism in {region} increased import costs by 15%.",
        "Anti-dumping duties of 28% placed on steel from {region} affecting downstream industries.",
        "Sudden tariff renegotiation collapsed trade agreement between {region} and major partner.",
        "Export controls on rare earth materials from {region} triggered global component shortage.",
    ],
    "demand": [
        "Post-pandemic restocking wave in {region} drove 280% surge in container bookings.",
        "Major retail platform in {region} launched same-day delivery; air freight capacity exhausted.",
        "Seasonal holiday spike in {region} outpaced available ocean freight capacity by 3×.",
        "Infrastructure stimulus package in {region} triggered steel and cement demand explosion.",
        "EV battery supply crunch in {region} caused automotive plant shutdowns.",
        "Commodity price speculation in {region} drove panic buying of raw materials.",
    ],
    "geopolitical": [
        "Trade sanctions imposed on {region} blocked access to SWIFT payment system for exporters.",
        "Territorial dispute in {region} forced commercial vessels to take 4,200 km detour.",
        "Coup in {region} closed borders for 3 weeks; perishable cargo losses exceeded $2B.",
        "Cyber attack on {region} customs clearance system paralysed cross-border freight.",
        "Naval blockade in {region} strait diverted 18% of global LNG shipments.",
        "Export ban on critical minerals from {region} triggered supply chain emergency in tech sector.",
    ],
}

RESPONSE_ACTIONS = {
    "weather": [
        "Activated alternative road routing bypassing flood zones; coordinated with insurance carriers.",
        "Pre-positioned emergency inventory at inland distribution centres ahead of storm.",
        "Negotiated spot air freight capacity to bypass closed sea lanes.",
    ],
    "port": [
        "Diverted vessels to secondary port 340 km away; arranged inland truck bridging.",
        "Engaged premium freight forwarder to expedite customs clearance via alternative process.",
        "Deployed emergency pop-up warehouse adjacent to terminal to buffer overflow.",
    ],
    "tariff": [
        "Accelerated import timeline to beat tariff effective date; stockpiled 90-day buffer.",
        "Initiated supplier diversification across three new source countries within 60 days.",
        "Filed tariff exclusion request and sourced from duty-free zone in parallel.",
    ],
    "demand": [
        "Chartered dedicated vessel; secured block space agreement with top-3 carriers.",
        "Shifted fulfillment to nearsourced supplier to reduce lead time from 45 to 12 days.",
        "Implemented demand sensing algorithm; adjusted safety stock thresholds dynamically.",
    ],
    "geopolitical": [
        "Activated dual-sourcing protocol; onboarded sanctioned-region-free supplier within 30 days.",
        "Rerouted via Cape of Good Hope; absorbed 14-day lead time increase in safety stock.",
        "Engaged trade compliance legal team; restructured entity structure to maintain access.",
    ],
}

OUTCOMES = ["successful", "partial", "failed"]
OUTCOME_WEIGHTS = [0.55, 0.35, 0.10]


def deterministic_uuid(seed: str) -> str:
    """Generate a deterministic UUID from a seed string for idempotency."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"scdf.seed.{seed}"))


def build_disruption_text(dtype: str, region: str, severity: int, year: int) -> str:
    template = random.choice(DISRUPTION_TEMPLATES[dtype])
    return (
        f"{template.format(region=region)} "
        f"Severity {severity}/10. Occurred in {year}."
    )


def build_response_text(dtype: str, region: str, actions: str, outcome: str, days: int) -> str:
    return (
        f"Response to {dtype} disruption in {region}. "
        f"Actions: {actions} "
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

                description = build_disruption_text(dtype, region, severity, year)
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
            actions = random.choice(RESPONSE_ACTIONS[rec["disruption_type"]])
            cost_k = round(random.uniform(50, 5000), 1)

            response_text = build_response_text(
                rec["disruption_type"], rec["region"], actions, outcome, actual_days
            )
            r_vec = get_embedding(response_text)

            response_points.append(
                PointStruct(
                    id=deterministic_uuid(f"rp-{rec['seed_key']}"),
                    vector=r_vec,
                    payload={
                        "response_id": response_id,
                        "disruption_id": rec["disruption_id"],
                        "actions_taken": actions,
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
