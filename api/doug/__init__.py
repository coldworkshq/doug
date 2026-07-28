"""Doug — risk-routed code review.

Routing is deterministic: no model reads a diff unless the score says it
should. The feature extractor is a pure function so the same code serves
the backtest CLI (over history) and the webhook (live).
"""

__version__ = "0.1.0"
