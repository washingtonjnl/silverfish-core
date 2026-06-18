"""The system database — Silverfish's own persistent store.

Always separate from the book library; here it holds only configuration. Lives
in the core (not the adapters) because it is our own schema, owned and evolved
by us, in contrast to the Calibre schema we merely read.
"""

from silverfish_core.system.db import SystemDatabase
from silverfish_core.system.models import Config, SystemBase

__all__ = [
    "Config",
    "SystemBase",
    "SystemDatabase",
]
