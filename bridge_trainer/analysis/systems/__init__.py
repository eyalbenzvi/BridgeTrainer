"""Bidding-system DSL for the analysis module.

interpreter.py turns an arbitrary user-entered auction into per-call
meanings and SeatConstraints, using a generic auction-role classifier
(code, shared by all systems) plus per-system YAML parameter tables
(sayc.yaml, two_over_one.yaml). Adding a system = adding a YAML table.
"""
from .interpreter import SystemTable, interpret_auction, load_system

__all__ = ["SystemTable", "interpret_auction", "load_system"]
