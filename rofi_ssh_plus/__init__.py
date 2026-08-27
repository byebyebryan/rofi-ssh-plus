"""A small, stateful SSH picker for Rofi script mode."""

from .model import HostRecord, HistoryState
from .state import StateStore

__all__ = ["HostRecord", "HistoryState", "StateStore"]
