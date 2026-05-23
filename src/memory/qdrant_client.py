"""
Qdrant client factory and collection setup for SCDF.

Collections
-----------
disruptions (1536-dim, cosine)
    Metadata schema:
        disruption_id:   str   — UUID, primary key
        disruption_type: str   — weather | port | tariff | demand | geopolitical
        region:          str   — Asia-Pacific | Europe | North America |
                                 Middle East | Latin America | Africa
        severity:        int   — 1 (minor) to 10 (catastrophic)
        year:            int   — calendar year of event
        resolution_days: int   — days until supply chain normalised
        resolved:        bool  — whether the disruption was fully resolved

responses (1536-dim, cosine)
    Metadata schema:
        response_id:     str   — UUID
        disruption_id:   str   — FK → disruptions.disruption_id
        actions_taken:   str   — free-text description of response actions
        outcome:         str   — successful | partial | failed
        resolution_days: int   — actual days to resolution
        cost_usd_k:      float — estimated cost in thousands USD

playbooks (1536-dim, cosine)
    Metadata schema:
        playbook_id:     str   — UUID
        disruption_type: str   — same enum as disruptions
        region:          str   — same enum as disruptions
        severity_band:   str   — low (1-3) | medium (4-6) | high (7-10)
        steps:           str   — JSON-encoded ordered list of action steps
        p10_days:        int   — optimistic resolution days
        p50_days:        int   — expected resolution days
        p90_days:        int   — pessimistic resolution days
"""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, CollectionInfo
from qdrant_client.http.exceptions import UnexpectedResponse

from src.config.settings import get_settings
from src.config.helicone import get_openai_client

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def get_qdrant_client() -> QdrantClient:
    """Return a connected QdrantClient using settings from .env."""
    settings = get_settings()
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def setup_collections(client: QdrantClient | None = None) -> None:
    """
    Create all three SCDF collections if they don't already exist.
    Idempotent — safe to call multiple times.
    """
    if client is None:
        client = get_qdrant_client()

    settings = get_settings()
    collections = [
        settings.qdrant_collection_disruptions,
        settings.qdrant_collection_responses,
        settings.qdrant_collection_playbooks,
    ]

    existing: list[str] = [c.name for c in client.get_collections().collections]

    for name in collections:
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM, distance=Distance.COSINE
                ),
            )
            print(f"  Created collection: {name}")
        else:
            print(f"  Collection already exists: {name}")


def get_embedding(text: str) -> list[float]:
    """
    Embed text using OpenAI text-embedding-3-small via Helicone proxy.

    Args:
        text: The text to embed.

    Returns:
        List of 1536 floats representing the embedding vector.
    """
    client = get_openai_client(agent_name="embedder")
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding
