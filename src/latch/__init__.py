"""LATCH — Look-Ahead Transhipment Connection Handler.

The decision layer for transhipment connections losing slack at Singapore:
it detects connections at risk, resolves what it can internally, and gets the
shipping line a real choice while options still exist.

Layout:
    models      frozen contracts shared with workstreams A and C
    state       risk lifecycle, as a validated transition table
    trace       append-only execution trace, cost included
    confidence  deterministic confidence from provenance
    locks       reservation store for contested resources
    tools       stubbed integrations plus failure injection
"""

__version__ = "0.1.0"
