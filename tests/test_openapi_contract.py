"""
OpenAPI contract validation tests.

This module validates that the committed ``openapi.yaml`` file at the
repository root is an exact structural match for the OpenAPI schema that
the FastAPI application generates at runtime.  This prevents undetectable
schema drift between the documented API contract (which external tools,
client-code generators, and contract-testing frameworks consume) and the
actual implementation.

Why this test exists
--------------------
The v5.0.0 specification (FR46) requires the CI pipeline to validate the
API contract.  A naïve approach (running model-related unit tests) does
not detect drift between the committed OpenAPI document and the live
schema.  For example, a developer could add a new error response to a
route decorator without regenerating the ``openapi.yaml`` file, causing
the committed document to silently fall behind the implementation.

This test catches that drift by:

1. Creating the application via the factory (which triggers the
   ``_customise_openapi_schema`` post-processing step that removes
   phantom 422 entries and adds global error responses).
2. Extracting the auto-generated OpenAPI schema as a Python dictionary.
3. Loading the committed ``openapi.yaml`` from the repository root.
4. Performing a deep structural comparison of both dictionaries.

If the two dictionaries differ, the test fails with a diagnostic message
instructing the developer to regenerate the ``openapi.yaml`` file.

How to regenerate openapi.yaml
------------------------------
Run the following command from the repository root::

    python -c "
    import yaml
    import application.server_factory
    application_instance = application.server_factory.create_application()
    schema = application_instance.openapi()
    with open('openapi.yaml', 'w', encoding='utf-8') as output_file:
        yaml.dump(schema, output_file, default_flow_style=False,
                  sort_keys=False, allow_unicode=True)
    "
"""

import json
import pathlib

import yaml

import application.server_factory

# The path to the committed OpenAPI specification file, resolved relative
# to this test file's location in the repository.  The test file lives at
# tests/test_openapi_contract.py, and the specification lives at the
# repository root (openapi.yaml), so we navigate two levels up.
_REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent
_COMMITTED_OPENAPI_SPECIFICATION_PATH = _REPOSITORY_ROOT / "openapi.yaml"


def _canonicalise_dictionary(value: object) -> str:
    """
    Convert a nested dictionary/list structure to a canonical JSON string
    with sorted keys and consistent formatting.

    This ensures that two structurally identical dictionaries produce
    identical string representations regardless of insertion order,
    enabling reliable equality comparison.

    Args:
        value: A dictionary, list, or primitive value to canonicalise.

    Returns:
        A deterministic JSON string representation of the input.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


class TestOpenApiContractAlignment:
    """
    Validate that the committed openapi.yaml matches the application's
    auto-generated OpenAPI schema.
    """

    def test_committed_openapi_specification_exists(self) -> None:
        """The openapi.yaml file must exist at the repository root."""
        assert _COMMITTED_OPENAPI_SPECIFICATION_PATH.exists(), (
            f"The committed OpenAPI specification file was not found at "
            f"{_COMMITTED_OPENAPI_SPECIFICATION_PATH}.  This file is "
            f"required for API contract validation and must be checked "
            f"into the repository."
        )

    def test_committed_openapi_specification_is_valid_yaml(self) -> None:
        """The openapi.yaml file must contain valid, parseable YAML."""
        with open(
            _COMMITTED_OPENAPI_SPECIFICATION_PATH,
            encoding="utf-8",
        ) as specification_file:
            parsed_content = yaml.safe_load(specification_file)

        assert isinstance(parsed_content, dict), (
            "The committed openapi.yaml file does not contain a valid "
            "OpenAPI specification.  Expected a YAML mapping (dictionary) "
            "at the top level."
        )

    def test_committed_specification_matches_generated_schema(self) -> None:
        """
        The committed openapi.yaml must be an exact structural match for
        the OpenAPI schema that the application generates at runtime.

        This is the core contract validation test.  It detects any drift
        between the documented API contract and the actual implementation,
        including:

        - New or removed endpoints
        - Changed request or response schemas
        - Added or removed error response definitions
        - Modified field descriptions or validation constraints

        If this test fails, regenerate the openapi.yaml file using the
        command documented in this module's docstring, then commit the
        updated file.
        """
        # Load the committed specification from the repository root.
        with open(
            _COMMITTED_OPENAPI_SPECIFICATION_PATH,
            encoding="utf-8",
        ) as specification_file:
            committed_specification = yaml.safe_load(specification_file)

        # Generate the live schema from the application factory.
        fastapi_application = application.server_factory.create_application()
        generated_schema = fastapi_application.openapi()

        # Compare the two schemas using canonical JSON serialisation.
        # This approach is order-independent (keys are sorted) and
        # produces a clear diff when the assertion fails.
        committed_canonical = _canonicalise_dictionary(committed_specification)
        generated_canonical = _canonicalise_dictionary(generated_schema)

        assert committed_canonical == generated_canonical, (
            "The committed openapi.yaml does not match the OpenAPI schema "
            "generated by the application.  This means the documented API "
            "contract has drifted from the implementation.\n\n"
            "To fix this, regenerate the openapi.yaml file by running:\n\n"
            '    python -c "\n'
            "    import yaml\n"
            "    import application.server_factory\n"
            "    application_instance = application.server_factory.create_application()\n"
            "    schema = application_instance.openapi()\n"
            "    with open('openapi.yaml', 'w', encoding='utf-8') as output_file:\n"
            "        yaml.dump(schema, output_file, default_flow_style=False,\n"
            "                  sort_keys=False, allow_unicode=True)\n"
            '    "\n\n'
            "Then commit the updated openapi.yaml file."
        )

    def test_generated_schema_contains_no_phantom_422_responses(self) -> None:
        """
        The generated OpenAPI schema must not contain any HTTP 422
        response entries.

        FastAPI auto-generates 422 (Unprocessable Entity) responses for
        every route that accepts a request body.  However, this service
        intercepts all validation errors via custom error handlers and
        returns 400 (Bad Request) with the ErrorResponse schema instead.
        The ``_customise_openapi_schema`` function in ``server_factory.py``
        removes these phantom 422 entries.

        This test verifies that the removal is effective and that no
        422 entries have been inadvertently reintroduced.
        """
        fastapi_application = application.server_factory.create_application()
        generated_schema = fastapi_application.openapi()

        for path, path_item in generated_schema.get("paths", {}).items():
            for http_method, operation in path_item.items():
                if isinstance(operation, dict) and "responses" in operation:
                    assert "422" not in operation["responses"], (
                        f"The OpenAPI schema contains a phantom 422 response "
                        f"for {http_method.upper()} {path}.  This service "
                        f"never returns HTTP 422 — all validation errors are "
                        f"returned as HTTP 400 with the ErrorResponse schema.  "
                        f"Ensure that _customise_openapi_schema() in "
                        f"server_factory.py is removing 422 entries correctly."
                    )

    def test_openapi_schema_is_cached_after_first_generation(self) -> None:
        """
        The ``customised_openapi()`` function caches the generated schema
        on ``fastapi_application.openapi_schema`` after the first call.
        Subsequent calls must return the cached schema (the same object
        identity) without regenerating it.

        This test exercises the cache return path at server_factory.py
        line 310: ``if fastapi_application.openapi_schema: return
        fastapi_application.openapi_schema``.

        Verifying object identity (``is``) rather than structural
        equality (``==``) confirms that the second call returns the
        exact same dictionary object from the cache, not a freshly
        generated copy.
        """
        fastapi_application = application.server_factory.create_application()

        # First call: generates and caches the schema.
        first_call_schema = fastapi_application.openapi()

        # Second call: must return the cached schema (same object).
        second_call_schema = fastapi_application.openapi()

        assert first_call_schema is second_call_schema, (
            "The second call to openapi() did not return the cached "
            "schema object.  The customised_openapi() function should "
            "cache the generated schema on fastapi_application.openapi_schema "
            "and return it on subsequent calls without regenerating."
        )

    def test_generated_schema_excludes_unused_validation_error_components(
        self,
    ) -> None:
        """
        The generated OpenAPI schema must not contain the
        HTTPValidationError or ValidationError component schemas.

        These schemas are auto-generated by FastAPI to support the
        phantom 422 responses.  Since the 422 responses are removed by
        ``_customise_openapi_schema``, these component schemas are
        unreferenced and should also be removed to keep the specification
        clean.
        """
        fastapi_application = application.server_factory.create_application()
        generated_schema = fastapi_application.openapi()

        component_schemas = generated_schema.get("components", {}).get(
            "schemas",
            {},
        )

        assert "HTTPValidationError" not in component_schemas, (
            "The OpenAPI schema still contains the HTTPValidationError "
            "component schema, which is unused after the removal of "
            "phantom 422 responses."
        )
        assert "ValidationError" not in component_schemas, (
            "The OpenAPI schema still contains the ValidationError "
            "component schema, which is unused after the removal of "
            "phantom 422 responses."
        )
