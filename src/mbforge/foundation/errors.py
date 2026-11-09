"""Typed MBForgeError exception hierarchy with structured context."""

from __future__ import annotations

from typing import Any, Literal

# Severity levels for hierarchical error categorization.
# Maps to standard log levels when recorded to the structured log/ring buffer.
Severity = Literal["debug", "info", "warning", "error", "fatal"]


class MBForgeError(Exception):
    """Base exception with HTTP status code, error code, and structured context.

    New (vs. the original two-arg form) fields:
        severity:  hierarchical log level — see the `Severity` literal.
                   Determines log record level AND frontend toast treatment.
        category:  module/layer tag (e.g. 'pipeline.runner', 'routers.library').
                   Defaults to the defining module of the exception subclass.
        context:   arbitrary JSON-serializable dict captured alongside the
                   record. Used by exception handlers and the diagnostics
                   ring buffer.
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        detail: str | None = None,
        severity: Severity = "error",
        category: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.detail = detail
        self.severity: Severity = severity
        self.category: str = category or self.__class__.__module__
        self.context: dict[str, Any] = context or {}
        super().__init__(message)


class ModelNotAvailableError(MBForgeError):
    status_code = 503
    error_code = "model_not_available"


class ValidationError(MBForgeError):
    status_code = 422
    error_code = "validation_error"


class FileAccessError(MBForgeError):
    status_code = 400
    error_code = "file_access_error"


class NotFoundError(MBForgeError):
    status_code = 404
    error_code = "not_found"


class PathTraversalError(MBForgeError):
    status_code = 403
    error_code = "path_traversal"


class ConflictError(MBForgeError):
    status_code = 409
    error_code = "conflict"


class ResourceNotAvailableError(MBForgeError):
    status_code = 503
    error_code = "resource_not_available"
