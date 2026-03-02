"""
Pydantic schemas for standardised error responses.

Every error response from this service follows the nested ``ErrorResponse``
→ ``ErrorDetail`` structure to ensure clients can rely on a consistent
error format across all endpoints.
"""

import pydantic


class ErrorDetail(pydantic.BaseModel):
    """
    Detailed error information nested inside the error response.

    The ``details`` field can be:
    - A descriptive string (for single-cause errors such as payload_too_large)
    - An array of validation error objects (for request_validation_failed)
    - Null or omitted when no additional context is available
    """

    code: str = pydantic.Field(
        ...,
        description="A machine-readable error code in snake_case format.",
    )

    message: str = pydantic.Field(
        ...,
        description=("A human-readable error description safe for display to end users."),
    )

    details: str | list | None = pydantic.Field(
        default=None,
        description=(
            "Additional context about the error, when available. May be a"
            " descriptive string, an array of validation error objects, or"
            " null."
        ),
    )

    correlation_id: str = pydantic.Field(
        ...,
        json_schema_extra={"format": "uuid"},
        description=("UUID v4 correlation identifier matching the X-Correlation-ID response header."),
    )

    model_config = pydantic.ConfigDict(extra="forbid")


class ErrorResponse(pydantic.BaseModel):
    """
    Standardised error response returned for all error conditions.

    Every error response from this service follows this nested structure
    to ensure clients can rely on a consistent error format.
    """

    error: ErrorDetail = pydantic.Field(
        ...,
        description="An object containing error details.",
    )

    model_config = pydantic.ConfigDict(extra="forbid")
