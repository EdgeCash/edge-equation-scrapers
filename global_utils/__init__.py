"""
global_utils — cross-sport helpers shared across the Edge Equation pipeline.

Anything truly sport-agnostic (Odds API quota tracking, future:
date/timezone helpers, request retry logic, generic CLV math) lives here
so MLB, NFL, NCAAF, etc. all consume the same implementation.

Sport-specific code (team mappings, projection models, bet types) stays
under its sport's directory — don't put MLB factors here.
"""

from .quota_log import log_quota, QUOTA_LOG_NAME, QUOTA_LOG_MAX_HISTORY

__all__ = ["log_quota", "QUOTA_LOG_NAME", "QUOTA_LOG_MAX_HISTORY"]
