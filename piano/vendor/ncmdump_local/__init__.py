"""Minimal MIT-licensed NCM core; no source-deleting CLI is included."""
from .ncm_core import NcmError, decrypt_to_file

__all__ = ["NcmError", "decrypt_to_file"]
