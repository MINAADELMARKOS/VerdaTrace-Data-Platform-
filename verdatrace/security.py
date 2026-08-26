"""Least-privilege authorization and secret-safe audit records."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Set

from .errors import AuthorizationError

LOGGER = logging.getLogger("verdatrace.audit")
SENSITIVE_KEY = re.compile(r"(secret|password|token|credential|api[_-]?key|raw[_-]?data)", re.I)

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "viewer": {"catalog:read", "quality:read", "result:read", "visualization:read"},
    "analyst": {
        "catalog:read",
        "quality:read",
        "result:read",
        "visualization:read",
        "analysis:execute",
        "dataset:export",
    },
    "ingestor": {
        "catalog:read",
        "quality:read",
        "result:read",
        "visualization:read",
        "dataset:ingest",
    },
    "steward": {
        "catalog:read",
        "quality:read",
        "result:read",
        "visualization:read",
        "analysis:execute",
        "dataset:ingest",
        "dataset:export",
        "metadata:update",
        "quality:evaluate",
    },
    "admin": {"*"},
}


def authorize(role: str, permission: str) -> None:
    granted = ROLE_PERMISSIONS.get(role, set())
    if "*" not in granted and permission not in granted:
        raise AuthorizationError(
            f"role '{role}' is not permitted to perform '{permission}'",
            corrective_action="Request the narrowest role that grants this operation.",
            details={"role": role, "permission": permission},
        )


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("[REDACTED]" if SENSITIVE_KEY.search(str(key)) else _sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: str
    actor: str
    operation: str
    target: str
    outcome: str
    correlation_id: str
    details: Dict[str, Any]


class AuditRecorder:
    """Records bounded metadata only; raw rows and secrets are never accepted."""

    def __init__(self) -> None:
        self.events: List[AuditEvent] = []

    def record(
        self,
        *,
        actor: str,
        operation: str,
        target: str,
        outcome: str,
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            operation=operation,
            target=target,
            outcome=outcome,
            correlation_id=correlation_id or str(uuid.uuid4()),
            details=_sanitize(details or {}),
        )
        self.events.append(event)
        LOGGER.info("audit_event=%s", asdict(event))
        return event
