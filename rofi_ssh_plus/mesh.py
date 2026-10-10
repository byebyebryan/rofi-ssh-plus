"""Select one Host Mesh authority behind the existing Python facade.

The default binds consumers to Mesh Plus's shared model and store. Explicit
ROFI_SSH_PLUS_MESH_BACKEND=legacy selects the bundled standalone implementation.
Missing selected providers fail at load time without a fallback.
"""

import os
import sys

from . import _legacy_mesh

backend = os.environ.get("ROFI_SSH_PLUS_MESH_BACKEND", "mesh-plus")
selected = _legacy_mesh
failure = None
if backend == "mesh-plus":
    try:
        from mesh_plus import authority as selected
        if type(getattr(selected, "MESH_SCHEMA_VERSION", None)) is not int or selected.MESH_SCHEMA_VERSION != 1:
            failure = "selected Mesh Plus authority is incompatible"
    except ImportError:
        failure = "selected Mesh Plus authority is unavailable"
elif backend != "legacy":
    failure = "invalid Host Mesh backend selection"

if failure:
    # Keep startup imports usable so CLI load emits the bounded typed error.
    for name, value in vars(_legacy_mesh).items():
        if not name.startswith("__"):
            globals()[name] = value

    def load_mesh(environ=None):
        raise _legacy_mesh.MeshError("invalid_config", failure)
else:
    # A module alias preserves patch seams and model-class identity.
    sys.modules[__name__] = selected
