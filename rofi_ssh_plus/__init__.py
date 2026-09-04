"""A small, stateful SSH picker for Rofi script mode."""

from .mesh import (
    Host,
    MeshConfig,
    MeshError,
    Route,
    RouteHealth,
    RouteHealthStore,
    SshPolicy,
    load_config,
    load_mesh,
    report_route,
)
from .model import HistoryState, HostRecord
from .state import StateStore

__all__ = [
    "HistoryState",
    "Host",
    "HostRecord",
    "MeshConfig",
    "MeshError",
    "Route",
    "RouteHealth",
    "RouteHealthStore",
    "SshPolicy",
    "StateStore",
    "load_config",
    "load_mesh",
    "report_route",
]
