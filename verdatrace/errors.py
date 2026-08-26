"""Structured platform errors."""

from __future__ import annotations

from typing import Any, Dict, Optional


class PlatformError(Exception):
    """Base error with a stable machine-readable code and corrective action."""

    code = "platform_error"

    def __init__(
        self,
        message: str,
        *,
        corrective_action: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.corrective_action = corrective_action
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "corrective_action": self.corrective_action,
            "details": self.details,
        }


class UnsupportedFormatError(PlatformError):
    code = "unsupported_file_format"


class InvalidSchemaError(PlatformError):
    code = "invalid_schema"


class AuthorizationError(PlatformError):
    code = "authorization_denied"


class ExternalSourceError(PlatformError):
    code = "external_source_unavailable"


class InsufficientDataError(PlatformError):
    code = "insufficient_data"


class UnsupportedVisualizationError(PlatformError):
    code = "unsupported_visualization"


class UnsupportedCrsError(PlatformError):
    code = "unsupported_crs"
