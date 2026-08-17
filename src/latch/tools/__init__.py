"""Tool layer: stubbed integrations plus deterministic failure injection."""

from latch.tools.base import (
    BASE_LATENCY_MS,
    CacheEntry,
    FailurePlan,
    NoFailures,
    ScriptedFailures,
    SeededFailures,
    ToolResult,
    ToolStatus,
    call,
)
from latch.tools.stubs import (
    ITTSlot,
    OutboundService,
    TransferMode,
    book_itt_slot,
    build_itt_inventory,
    connection_density_score,
    itt_transit_minutes,
    query_itt_slot,
    query_outbound_services,
    send_options_to_line,
)

__all__ = [
    "BASE_LATENCY_MS",
    "CacheEntry",
    "FailurePlan",
    "ITTSlot",
    "NoFailures",
    "OutboundService",
    "ScriptedFailures",
    "SeededFailures",
    "ToolResult",
    "ToolStatus",
    "TransferMode",
    "book_itt_slot",
    "build_itt_inventory",
    "call",
    "connection_density_score",
    "itt_transit_minutes",
    "query_itt_slot",
    "query_outbound_services",
    "send_options_to_line",
]
