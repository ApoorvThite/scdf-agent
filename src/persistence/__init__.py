"""
SCDF persistence layer — DynamoDB storage for flow run results.
"""

from src.persistence.dynamodb import (
    save_playbook_result,
    get_playbook_by_signal_id,
    list_recent_playbooks,
    ensure_table_exists,
)

__all__ = [
    "save_playbook_result",
    "get_playbook_by_signal_id",
    "list_recent_playbooks",
    "ensure_table_exists",
]
