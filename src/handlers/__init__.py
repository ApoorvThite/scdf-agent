"""
SCDF Lambda handler — AWS Lambda entry point for signal processing.
"""

from src.handlers.signal_handler import handler, local_invoke

__all__ = ["handler", "local_invoke"]
