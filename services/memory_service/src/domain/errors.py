from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: str
    message: str


class IngestError(Exception):
    code = "INGEST_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_error_info(self) -> ErrorInfo:
        return ErrorInfo(code=self.code, message=str(self))


class ConfigError(IngestError):
    code = "CONFIG_ERROR"


class InvalidInputError(IngestError):
    code = "INVALID_INPUT"


class UnsupportedSourceError(IngestError):
    code = "UNSUPPORTED_SOURCE"


class AdapterError(IngestError):
    code = "ADAPTER_ERROR"


class RetryLaterError(AdapterError):
    code = "RETRY_LATER"


class AccessRestrictedError(AdapterError):
    code = "ACCESS_RESTRICTED"


class IndexError(IngestError):
    code = "INDEX_ERROR"


class EMOSAuthError(IngestError):
    code = "EMOS_AUTH"


class EMOSNetworkError(IngestError):
    code = "EMOS_NETWORK"


class EMOSValidationError(IngestError):
    code = "EMOS_VALIDATION"


class EMOSServerError(IngestError):
    code = "EMOS_SERVER"


class SegmentsFailedError(IngestError):
    code = "SEGMENTS_FAILED"
