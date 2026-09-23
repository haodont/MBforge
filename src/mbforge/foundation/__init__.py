"""MBForge utility package.

Re-exports commonly used helpers from the submodules so callers can
import from ``mbforge.foundation`` directly.  Submodules remain the source
of truth for each helper's implementation.
"""

from mbforge.foundation.config import (
    AppConfig,
    LLMConfig,
    load_global_config,
    save_global_config,
)
from mbforge.foundation.files import sha256_file, sha256_text
from mbforge.foundation.ids import deterministic_id, short_id, stable_id
from mbforge.foundation.text import split_text_chunks, truncate_text

__all__ = [
    "short_id",
    "deterministic_id",
    "stable_id",
    "sha256_file",
    "sha256_text",
    "safe_filename",
    "truncate_text",
    "split_text_chunks",
    "load_global_config",
    "save_global_config",
    "AppConfig",
    "LLMConfig",
]
