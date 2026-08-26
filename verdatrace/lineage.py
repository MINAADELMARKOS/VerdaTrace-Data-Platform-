"""Dataset and result lineage graph."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, List


@dataclass(frozen=True)
class LineageStep:
    stage: str
    input_ref: str
    output_ref: str
    operation: str
    timestamp: str


class LineageTracker:
    def __init__(self) -> None:
        self.steps: List[LineageStep] = []

    def add(self, stage: str, input_ref: str, output_ref: str, operation: str) -> None:
        self.steps.append(
            LineageStep(
                stage=stage,
                input_ref=input_ref,
                output_ref=output_ref,
                operation=operation,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    def as_list(self) -> List[Dict[str, str]]:
        return [asdict(step) for step in self.steps]
