#!/usr/bin/env python3
"""
SCDF Week 1 — Connection health check.
Runs every integration in sequence and prints pass/fail.

Usage:
    python scripts/test_connections.py
"""

import sys
import os

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> bool:
    try:
        detail = fn()
        results.append((name, True, detail or "OK"))
        return True
    except Exception as e:
        results.append((name, False, str(e)[:120]))
        return False


# ── 1. Settings ────────────────────────────────────────────────────────────────
def check_settings():
    from src.config.settings import get_settings
    s = get_settings()
    assert s.openai_api_key, "OPENAI_API_KEY not set"
    assert s.helicone_api_key, "HELICONE_API_KEY not set"
    return (
        f"project={s.project_name} env={s.environment} "
        f"model_primary={s.model_primary} model_debate={s.model_debate}"
    )


# ── 2. OpenAI via Helicone ─────────────────────────────────────────────────────
def check_openai_helicone():
    from src.config.helicone import get_openai_client
    client = get_openai_client(agent_name="connection-test")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Reply with the single word: PONG"}],
        max_tokens=5,
    )
    reply = resp.choices[0].message.content.strip()
    return f"model={resp.model} reply={reply!r}"


# ── 3. Helicone dashboard receiving requests ───────────────────────────────────
def check_helicone_dashboard():
    from src.config.helicone import get_openai_client
    # A second distinct call with a unique property so it's easy to find in the UI
    client = get_openai_client(agent_name="helicone-dashboard-test")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Reply with: HELICONE_OK"}],
        max_tokens=5,
    )
    return f"request_id={resp.id[:20]}... model={resp.model}"


# ── 4. Qdrant reachable and collections exist ──────────────────────────────────
def check_qdrant():
    from src.memory.qdrant_client import get_qdrant_client, setup_collections
    client = get_qdrant_client()
    # Ensure collections exist
    setup_collections(client)
    collections = [c.name for c in client.get_collections().collections]
    from src.config.settings import get_settings
    s = get_settings()
    required = [
        s.qdrant_collection_disruptions,
        s.qdrant_collection_responses,
        s.qdrant_collection_playbooks,
    ]
    missing = [r for r in required if r not in collections]
    if missing:
        raise RuntimeError(f"Missing collections: {missing}")
    return f"collections={collections}"


# ── 5. Langfuse reachable and accepting events ─────────────────────────────────
def check_langfuse():
    from langfuse import Langfuse
    from src.config.settings import get_settings
    s = get_settings()
    lf = Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        host=s.langfuse_host,
    )
    trace = lf.trace(name="scdf-connection-test", metadata={"week": 1})
    trace.span(name="health-check", input={"test": True}, output={"status": "ok"})
    lf.flush()
    return f"trace_id={trace.id}"


# ── 6. Mock signal generator ───────────────────────────────────────────────────
def check_mock_signals():
    from src.signals.mock_generator import generate_mock_signal, DisruptionSignal
    types = ["weather", "port", "tariff", "demand", "geopolitical"]
    for t in types:
        sig = generate_mock_signal(disruption_type=t)
        assert isinstance(sig, DisruptionSignal)
        assert sig.disruption_type == t
        assert 1 <= sig.severity_score <= 10
    return f"generated={len(types)} signals, all valid"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    console.rule("[bold blue]SCDF Week 1 — Connection Health Check[/bold blue]")
    console.print()

    checks = [
        ("Settings loaded correctly", check_settings),
        ("OpenAI API reachable via Helicone proxy", check_openai_helicone),
        ("Helicone dashboard receiving requests", check_helicone_dashboard),
        ("Qdrant reachable and collections exist", check_qdrant),
        ("Langfuse reachable and accepting events", check_langfuse),
        ("Mock signal generator produces valid signals", check_mock_signals),
    ]

    for name, fn in checks:
        console.print(f"  [cyan]→[/cyan] {name}...", end=" ")
        passed = check(name, fn)
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        detail = results[-1][2]
        console.print(f"{status}  [dim]{detail}[/dim]")

    console.print()

    # Summary table
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Check", style="dim", width=48)
    table.add_column("Status", width=8)
    table.add_column("Detail")

    passed_count = 0
    for name, ok, detail in results:
        icon = "[green]✓ PASS[/green]" if ok else "[red]✗ FAIL[/red]"
        if ok:
            passed_count += 1
        table.add_row(name, icon, f"[dim]{detail}[/dim]")

    console.print(table)

    total = len(results)
    if passed_count == total:
        console.print(
            f"[bold green]Week 1 complete — {passed_count}/{total} checks passed.[/bold green]\n"
        )
    else:
        console.print(
            f"[bold yellow]Week 1 partial — {passed_count}/{total} checks passed. "
            f"Fix failures above before proceeding.[/bold yellow]\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
