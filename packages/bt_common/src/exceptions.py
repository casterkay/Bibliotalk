"""Typed domain exceptions for agent workflows."""


class EMOSError(Exception):
    """Base exception for EMOS-related failures."""


class EMOSConnectionError(EMOSError):
    """Raised when connecting to EMOS fails after retries."""


class EMOSNotFoundError(EMOSError):
    """Raised when EMOS reports requested entity not found."""


class EMOSValidationError(EMOSError):
    """Raised when request data fails EMOS validation."""


class CitationValidationError(Exception):
    """Raised when citation payload is malformed."""


class AgentNotFoundError(Exception):
    """Raised when a requested agent does not exist."""
