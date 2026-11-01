"""Domain errors raised by the ingestion service."""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for expected ingestion errors."""


class JobNotFound(IngestionError):
    """The requested job does not exist for this tenant/application."""


class JobNotCompleted(IngestionError):
    """A result was requested before the job reached a terminal state."""


class JobAlreadyRunning(IngestionError):
    """The job is already being processed by this worker."""


class InvalidIdentifier(IngestionError):
    """A tenant, application or job identifier is not path-safe."""


class PDFValidationError(IngestionError):
    """The uploaded file is not a usable, unencrypted PDF."""


class OCREngineUnavailable(IngestionError):
    """The OCR engine or its system dependency is not available."""
