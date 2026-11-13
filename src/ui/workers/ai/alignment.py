"""Compatibility exports for AI lyrics alignment helpers."""
from __future__ import annotations

from . import alignment_candidates as _candidates
from . import alignment_tail as _tail
from . import alignment_viterbi as _viterbi
from .alignment_candidates import *
from .alignment_tail import *
from .alignment_viterbi import *

__all__ = _candidates.__all__ + _tail.__all__ + _viterbi.__all__
