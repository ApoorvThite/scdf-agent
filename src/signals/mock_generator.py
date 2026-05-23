"""
Mock disruption signal generator — simulates Upstash Redis Streams for local dev.

Run directly to print a sample signal:
    python -m src.signals.mock_generator
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Generator

from pydantic import BaseModel, Field


# ── Pydantic model ─────────────────────────────────────────────────────────────

class DisruptionSignal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    disruption_type: str  # weather | port | tariff | demand | geopolitical
    region: str           # Asia-Pacific | Europe | North America | Middle East | Latin America | Africa
    severity_score: int = Field(ge=1, le=10)
    description: str
    affected_routes: list[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str


# ── Disruption templates ───────────────────────────────────────────────────────

TEMPLATES: list[dict] = [
    {
        "disruption_type": "port",
        "region": "Asia-Pacific",
        "severity_score_range": (6, 10),
        "descriptions": [
            "Port of Shanghai labor strike halts container operations for major terminals.",
            "Typhoon Mawar forces closure of Port of Kaohsiung — 300+ vessels rerouted.",
            "Port of Singapore congestion spike: average dwell time exceeds 8 days.",
            "Port of Busan crane operator strike enters third week; 40% capacity reduction.",
        ],
        "affected_routes": [
            ["Trans-Pacific Eastbound", "Intra-Asia"],
            ["Asia-Europe Westbound", "Trans-Pacific Westbound"],
        ],
        "sources": ["Lloyd's List", "Port Authority Bulletin", "Reuters Maritime"],
    },
    {
        "disruption_type": "tariff",
        "region": "North America",
        "severity_score_range": (4, 8),
        "descriptions": [
            "US announces 25% Section 301 tariffs on $300B of Chinese electronics imports.",
            "USMCA dispute triggers retaliatory Canadian tariffs on US agricultural exports.",
            "EU imposes anti-dumping duties on Chinese steel — affects NA re-export flows.",
            "US Treasury adds 12 entities to SDN list; downstream component shortage expected.",
        ],
        "affected_routes": [
            ["Trans-Pacific Eastbound", "US-Canada Overland"],
            ["Trans-Atlantic", "US-Mexico Land Bridge"],
        ],
        "sources": ["Federal Register", "USTR Press Release", "Bloomberg Trade"],
    },
    {
        "disruption_type": "weather",
        "region": "Europe",
        "severity_score_range": (3, 8),
        "descriptions": [
            "Rhine River water levels critical — barge capacity down 60% across Germany.",
            "Storm Ciarán disrupts UK-Dover Strait ferry services; 48-hour closure expected.",
            "Arctic cold snap freezes Baltic ports; icebreaker support requested.",
            "Mediterranean heatwave triggers Suez Canal speed restrictions to reduce wake.",
        ],
        "affected_routes": [
            ["Europe Intra-Regional", "North Sea Feeder"],
            ["Asia-Europe Westbound", "Suez Canal"],
        ],
        "sources": ["European Waterways Commission", "Met Office", "Eurostat Freight"],
    },
    {
        "disruption_type": "demand",
        "region": "Latin America",
        "severity_score_range": (4, 7),
        "descriptions": [
            "Black Friday demand spike: Brazil e-commerce volumes up 340% YoY — air freight saturated.",
            "Argentina currency devaluation triggers panic import buying; port congestion +85%.",
            "Mexico nearshoring boom drives 200% increase in cross-border truck demand.",
            "Colombia coffee harvest shortfall triggers commodity futures spike; container bookings surge.",
        ],
        "affected_routes": [
            ["US-Latin America", "Intra-Americas"],
            ["Trans-Atlantic Southbound", "Intra-Americas"],
        ],
        "sources": ["ECLAC Trade Monitor", "Drewry Supply Chain Advisors", "Freightos Index"],
    },
    {
        "disruption_type": "geopolitical",
        "region": "Middle East",
        "severity_score_range": (7, 10),
        "descriptions": [
            "Houthi attacks in Red Sea force major carriers to reroute via Cape of Good Hope.",
            "Iran strait of Hormuz tension escalates — insurance premiums surge 400%.",
            "Suez Canal transit restrictions imposed for vessels flagged in sanctioned states.",
            "Yemen ceasefire collapse triggers Bab-el-Mandeb closure threat; 12% of global trade at risk.",
        ],
        "affected_routes": [
            ["Asia-Europe Westbound", "Suez Canal"],
            ["Middle East Gulf", "Trans-Atlantic"],
        ],
        "sources": ["UKMTO Maritime Security", "IMB Piracy Center", "S&P Global Platts"],
    },
]

REGIONS = [
    "Asia-Pacific", "Europe", "North America",
    "Middle East", "Latin America", "Africa",
]


# ── Generator functions ────────────────────────────────────────────────────────

def generate_mock_signal(
    disruption_type: str | None = None,
    severity: int | None = None,
) -> DisruptionSignal:
    """
    Generate a single realistic DisruptionSignal.

    Args:
        disruption_type: Force a specific type (weather|port|tariff|demand|geopolitical).
                         Defaults to random selection.
        severity:        Force a specific severity score (1-10). Defaults to random.

    Returns:
        A validated DisruptionSignal instance.
    """
    if disruption_type:
        template = next(
            (t for t in TEMPLATES if t["disruption_type"] == disruption_type),
            random.choice(TEMPLATES),
        )
    else:
        template = random.choice(TEMPLATES)

    low, high = template["severity_score_range"]
    actual_severity = severity if severity is not None else random.randint(low, high)

    region = template["region"] if random.random() > 0.2 else random.choice(REGIONS)
    routes = random.choice(template["affected_routes"])
    description = random.choice(template["descriptions"])
    source = random.choice(template["sources"])

    return DisruptionSignal(
        disruption_type=template["disruption_type"],
        region=region,
        severity_score=min(10, max(1, actual_severity)),
        description=description,
        affected_routes=routes,
        source=source,
    )


def stream_signals(
    interval_seconds: float = 5.0,
    count: int = 10,
    disruption_type: str | None = None,
) -> Generator[DisruptionSignal, None, None]:
    """
    Yield disruption signals at a fixed interval, simulating a Redis Stream.

    Args:
        interval_seconds: Seconds between signals.
        count:            Total number of signals to yield. Use -1 for infinite.
        disruption_type:  Optional filter to a single disruption type.

    Yields:
        DisruptionSignal instances.
    """
    emitted = 0
    while count == -1 or emitted < count:
        yield generate_mock_signal(disruption_type=disruption_type)
        emitted += 1
        if count == -1 or emitted < count:
            time.sleep(interval_seconds)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    signal = generate_mock_signal()
    print(json.dumps(signal.model_dump(mode="json"), indent=2, default=str))
