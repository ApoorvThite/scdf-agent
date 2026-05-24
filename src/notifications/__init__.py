"""
SCDF notifications layer — SNS alert routing by risk level.
"""

from src.notifications.sns_publisher import publish_playbook_alert

__all__ = ["publish_playbook_alert"]
