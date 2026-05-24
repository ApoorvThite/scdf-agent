"""
Qdrant semantic retrieval engine for SCDF.

Handles all vector search and record formatting for the Impact Modeler agent.
Uses cosine similarity search against the disruptions collection, with optional
metadata filters that broaden automatically when fewer than 2 results match.

Run standalone to test:
    python -m src.memory.qdrant_retrieval
"""

import logging
import uuid

from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.memory.qdrant_client import get_embedding, get_qdrant_client
from src.config.settings import get_settings
from src.models.outputs import HistoricalPrecedent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

def build_retrieval_query(disruption_type: str, region: str, severity_score: int, affected_kpis: list[str] | None = None) -> str:
    """
    Construct a rich natural-language query for semantic similarity search.

    Weights disruption_type and region most heavily; adds KPI context.
    The query is optimised for the text-embedding-3-small model.
    """
    kpi_str = " ".join(affected_kpis or ["lead_time", "inventory", "service_level"])
    severity_label = (
        "minor" if severity_score <= 3
        else "moderate" if severity_score <= 6
        else "severe" if severity_score <= 8
        else "catastrophic"
    )
    return (
        f"{disruption_type} disruption {region} supply chain "
        f"{severity_label} severity {severity_score} "
        f"affecting {kpi_str} freight delay resolution"
    )


# ---------------------------------------------------------------------------
# Primary retrieval
# ---------------------------------------------------------------------------

def retrieve_similar_disruptions(
    disruption_type: str,
    region: str,
    description: str,
    severity_score: int = 5,
    affected_kpis: list[str] | None = None,
    top_k: int = 3,
) -> list[dict]:
    """
    Semantic search in Qdrant disruptions collection.

    Strategy:
      1. Search with exact disruption_type + region filter + resolved=True.
      2. If fewer than 2 results, broaden to disruption_type only.
      3. If still empty, return unfiltered results.

    Returns:
        List of dicts with all payload fields plus 'id' and 'score'.
        Returns empty list on connection failure (with warning logged).
    """
    client = get_qdrant_client()
    settings = get_settings()
    collection = settings.qdrant_collection_disruptions

    # Build embedding from the signal description + semantic query
    query_text = f"{description} {build_retrieval_query(disruption_type, region, severity_score, affected_kpis)}"

    try:
        embedding = get_embedding(query_text)
    except Exception as exc:
        logger.warning(f"Embedding failed: {exc}")
        return []

    def _search(filt: Filter | None) -> list[dict]:
        try:
            results = client.search(
                collection_name=collection,
                query_vector=embedding,
                query_filter=filt,
                limit=top_k,
                score_threshold=0.0,
            )
            return [
                {"id": str(r.id), "score": r.score, **(r.payload or {})}
                for r in results
            ]
        except Exception as exc:
            logger.warning(f"Qdrant search failed: {exc}")
            return []

    # Attempt 1: strict filter — type + region + resolved
    strict_filter = Filter(
        must=[
            FieldCondition(key="disruption_type", match=MatchValue(value=disruption_type)),
            FieldCondition(key="region", match=MatchValue(value=region)),
            FieldCondition(key="resolved", match=MatchValue(value=True)),
        ]
    )
    records = _search(strict_filter)

    # Attempt 2: broaden to type-only if too few results
    if len(records) < 2:
        logger.info(f"Broadening retrieval: only {len(records)} results for type+region filter")
        type_filter = Filter(
            must=[
                FieldCondition(key="disruption_type", match=MatchValue(value=disruption_type)),
                FieldCondition(key="resolved", match=MatchValue(value=True)),
            ]
        )
        records = _search(type_filter)

    # Attempt 3: no filter
    if not records:
        logger.info("Broadening retrieval: no type filter")
        records = _search(None)

    return records[:top_k]


# ---------------------------------------------------------------------------
# Response record lookup
# ---------------------------------------------------------------------------

def retrieve_response_records(disruption_ids: list[str]) -> list[dict]:
    """
    Fetch response records linked to the given disruption IDs.

    Uses Qdrant scroll (payload filter) rather than vector search,
    since we need records by FK (disruption_id), not by similarity.

    Returns:
        List of response record dicts. May be shorter than disruption_ids
        if some have no matching response.
    """
    if not disruption_ids:
        return []

    client = get_qdrant_client()
    settings = get_settings()
    collection = settings.qdrant_collection_responses
    results = []

    for d_id in disruption_ids:
        try:
            records, _ = client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="disruption_id", match=MatchValue(value=d_id))]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if records:
                results.append({"id": str(records[0].id), **(records[0].payload or {})})
        except Exception as exc:
            logger.warning(f"Response lookup failed for disruption_id={d_id}: {exc}")

    return results


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_precedents(
    disruption_records: list[dict],
    response_records: list[dict],
) -> list[HistoricalPrecedent]:
    """
    Merge disruption and response records into HistoricalPrecedent models.

    Zips by index — response_records may be shorter; missing responses get
    fallback placeholder values so the precedent list length is maintained.
    """
    precedents: list[HistoricalPrecedent] = []
    resp_by_d_id = {r.get("disruption_id"): r for r in response_records}

    for drec in disruption_records:
        d_id = drec.get("disruption_id", drec.get("id", str(uuid.uuid4())))
        resp = resp_by_d_id.get(d_id, {})

        # Parse actions_taken — stored as a single string in seed data
        raw_actions = resp.get("actions_taken", "")
        if isinstance(raw_actions, list):
            actions = raw_actions
        elif raw_actions:
            # Split on semicolons or sentence boundaries
            actions = [a.strip() for a in raw_actions.replace(";", ".").split(".") if a.strip()]
        else:
            actions = ["Response actions not recorded"]

        precedents.append(
            HistoricalPrecedent(
                record_id=drec.get("id", str(uuid.uuid4())),
                similarity_score=min(1.0, max(0.0, float(drec.get("score", 0.5)))),
                disruption_type=drec.get("disruption_type", "unknown"),
                region=drec.get("region", "unknown"),
                description=drec.get("description", "No description available"),
                resolution_days=int(resp.get("resolution_days", drec.get("resolution_days", 14))),
                actions_taken=actions[:5],  # cap at 5 actions
                outcome=resp.get("outcome", "unknown"),
            )
        )

    return precedents


def get_retrieval_quality_score(precedents: list[HistoricalPrecedent]) -> float:
    """Return average similarity score across all precedents, or 0.0 if empty."""
    if not precedents:
        return 0.0
    return round(sum(p.similarity_score for p in precedents) / len(precedents), 4)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.console import Console
    from rich.pretty import Pretty

    console = Console()
    console.rule("[bold cyan]SCDF Qdrant Retrieval Test[/bold cyan]")

    records = retrieve_similar_disruptions(
        disruption_type="port",
        region="Asia-Pacific",
        description="Port of Shanghai crane operator strike halts container operations",
        severity_score=8,
    )
    console.print(f"Found {len(records)} disruption records")
    for r in records:
        console.print(f"  score={r.get('score', 0):.3f}  type={r.get('disruption_type')}  region={r.get('region')}")

    if records:
        d_ids = [r.get("disruption_id", "") for r in records]
        resp_records = retrieve_response_records(d_ids)
        console.print(f"Found {len(resp_records)} response records")

        precedents = format_precedents(records, resp_records)
        console.print(Pretty([p.model_dump() for p in precedents]))
        console.print(f"Retrieval quality: {get_retrieval_quality_score(precedents):.3f}")

    console.rule("[bold green]Done[/bold green]")
