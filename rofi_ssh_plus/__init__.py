"""A small, stateful SSH picker for Rofi script mode."""

from importlib import import_module

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


def __getattr__(name):
    """Keep public exports available without loading picker code for Mesh."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = (
        "state" if name == "StateStore"
        else "model" if name in {"HistoryState", "HostRecord"}
        else "mesh"
    )
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
