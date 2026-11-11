"""Agent-callable capability registry."""

from . import api_surface as _api_surface  # noqa: F401 - registers read capabilities
from . import read as _read  # noqa: F401 - registers read capabilities
from . import (
    read_molecules as _read_molecules,  # noqa: F401 — registers read capabilities
)
from . import read_patent as _read_patent  # noqa: F401 — registers read capabilities
from . import (
    read_review as _read_review,  # noqa: F401 — registers read capabilities
)
from . import (
    read_structures as _read_structures,  # noqa: F401 — registers read capabilities
)
from . import read_visual as _read_visual  # noqa: F401 — registers read capabilities
from . import write as _write  # noqa: F401 — registers write capabilities
from .registry import (
    Capability,
    CapabilityContext,
    CapabilityMode,
    CapabilityResult,
    all_capabilities,
    get_capability,
    invoke,
    register,
)

__all__ = [
    "Capability",
    "CapabilityContext",
    "CapabilityMode",
    "CapabilityResult",
    "all_capabilities",
    "get_capability",
    "invoke",
    "register",
]
