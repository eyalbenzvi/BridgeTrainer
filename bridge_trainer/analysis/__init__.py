"""Bidding-analysis module: user-entered deal + auction -> expert report.

Isolated from the UI (see analysis/server.py for the local web front end).
Reuses the existing engine layers wholesale: constraints/dealing/dd/scoring.
All numeric conclusions come from local deterministic computation; the LLM
(if enabled) only phrases the report.
"""
