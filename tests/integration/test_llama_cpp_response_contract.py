"""
Consumer-side contract test for the llama.cpp ``POST /v1/chat/completions`` response schema.

This module pins the exact response body structure that the service
depends on from the llama.cpp server.  If the llama.cpp API changes its
response format, this test will fail before any other test — providing
a clear, named signal of the root cause.

No running llama.cpp server is required.  All HTTP interactions are
replaced with in-memory mock responses expressed as Python dictionaries,
as required by the specification (Section 20).

The four properties verified by ``test_llama_cpp_response_contract`` are:

1. A well-formed response body yields ``choices[0].message.content``
   as a non-empty string with leading and trailing whitespace stripped.

2. A connection error produces
   ``LargeLanguageModelServiceUnavailableError``, which the error-handling
   layer classifies as ``upstream_service_unavailable`` (HTTP 502).

3. A response body with a missing ``choices`` field produces
   ``PromptEnhancementError``, which the error-handling layer also
   classifies as ``upstream_service_unavailable`` (HTTP 502).

4. A response body with an empty ``choices`` array produces
   ``PromptEnhancementError``, classified as ``upstream_service_unavailable``
   (HTTP 502).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import application.exceptions
import application.integrations.llama_cpp_client

# ---------------------------------------------------------------------------
# Representative well-formed response body from llama.cpp
# POST /v1/chat/completions — expressed as a Python dictionary so the
# contract is readable without parsing JSON.
# ---------------------------------------------------------------------------
WELL_FORMED_RESPONSE_BODY_FROM_LLAMA_CPP: dict = {
    "choices": [
        {
            "message": {
                "content": (
                    "A majestic mountain landscape at golden hour,"
                    " dramatic volumetric lighting, photorealistic, 8K resolution"
                ),
            },
            "finish_reason": "stop",
        }
    ]
}


def _build_llama_cpp_client_for_contract_testing() -> application.integrations.llama_cpp_client.LlamaCppClient:
    """
    Construct a ``LlamaCppClient`` with minimal configuration for use in
    contract tests.  The HTTP client is replaced by a mock in each test,
    so the base URL and timeout values here are placeholders only.
    """
    return application.integrations.llama_cpp_client.LlamaCppClient(
        base_url_of_large_language_model_server="http://localhost:8080",
        request_timeout_in_seconds=30.0,
    )


def _build_mock_of_successful_http_response(
    response_body: dict,
) -> MagicMock:
    """
    Build a mock ``httpx.Response`` that mimics a successful 200 reply
    from the llama.cpp server.

    The mock includes the ``headers`` and ``content`` attributes that
    ``LlamaCppClient`` inspects for streaming response detection
    (Content-Type must not be ``text/event-stream``) and response body
    size enforcement (``len(response.content)`` must not exceed the
    configured maximum).
    """
    serialised_body = json.dumps(response_body).encode("utf-8")
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = response_body
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = serialised_body
    return mock_response


@pytest.mark.asyncio
async def test_llama_cpp_response_contract() -> None:
    """
    Consumer-side contract test for the llama.cpp ``POST /v1/chat/completions``
    response schema (specification Section 20).

    Assertion 1 — correct extraction from a well-formed response:
        ``choices[0].message.content`` is returned as a non-empty string
        with leading and trailing whitespace stripped.

    Assertion 2 — connection error classification:
        A network-level ``ConnectError`` raises
        ``LargeLanguageModelServiceUnavailableError``, which the
        error-handling layer maps to the ``upstream_service_unavailable``
        error code (HTTP 502).

    Assertion 3 — missing ``choices`` field classification:
        A response body that omits the ``choices`` key entirely raises
        ``PromptEnhancementError``, which the error-handling layer also
        maps to ``upstream_service_unavailable`` (HTTP 502).

    Assertion 4 — empty ``choices`` array classification:
        A response body whose ``choices`` array contains zero elements
        raises ``PromptEnhancementError``, classified as
        ``upstream_service_unavailable`` (HTTP 502).
    """
    client = _build_llama_cpp_client_for_contract_testing()
    mock_http_client = AsyncMock()
    client.http_client = mock_http_client

    # ------------------------------------------------------------------
    # Assertion 1: well-formed response → correct extraction
    # ------------------------------------------------------------------
    mock_http_client.post = AsyncMock(
        return_value=_build_mock_of_successful_http_response(WELL_FORMED_RESPONSE_BODY_FROM_LLAMA_CPP)
    )
    extracted_enhanced_prompt = await client.enhance_prompt("a mountain at sunset")
    expected_content = WELL_FORMED_RESPONSE_BODY_FROM_LLAMA_CPP["choices"][0]["message"]["content"]

    assert isinstance(extracted_enhanced_prompt, str)
    assert len(extracted_enhanced_prompt) > 0
    assert extracted_enhanced_prompt == expected_content

    # ------------------------------------------------------------------
    # Assertion 2: connection error → upstream_service_unavailable
    # ------------------------------------------------------------------
    mock_http_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
        await client.enhance_prompt("a mountain at sunset")

    # ------------------------------------------------------------------
    # Assertion 3: missing choices field → upstream_service_unavailable
    # ------------------------------------------------------------------
    mock_http_client.post = AsyncMock(return_value=_build_mock_of_successful_http_response({}))
    with pytest.raises(application.exceptions.PromptEnhancementError):
        await client.enhance_prompt("a mountain at sunset")

    # ------------------------------------------------------------------
    # Assertion 4: empty choices array → upstream_service_unavailable
    # ------------------------------------------------------------------
    mock_http_client.post = AsyncMock(return_value=_build_mock_of_successful_http_response({"choices": []}))
    with pytest.raises(application.exceptions.PromptEnhancementError):
        await client.enhance_prompt("a mountain at sunset")

    await client.close()
