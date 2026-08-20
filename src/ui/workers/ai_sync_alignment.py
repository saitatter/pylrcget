"""Compatibility exports for AI lyrics alignment helpers."""
from __future__ import annotations

from . import ai_sync_alignment_candidates as _candidates
from . import ai_sync_alignment_tail as _tail
from . import ai_sync_alignment_viterbi as _viterbi
from .ai_sync_alignment_candidates import *  # noqa: F401,F403
from .ai_sync_alignment_tail import *  # noqa: F401,F403
from .ai_sync_alignment_viterbi import *  # noqa: F401,F403

__all__ = _candidates.__all__ + _tail.__all__ + _viterbi.__all__
