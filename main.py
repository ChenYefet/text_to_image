"""
Thin re-export shim for the Uvicorn entry point.

Uvicorn is configured with ``main:fastapi_application`` as its import
target (both in the Dockerfile CMD and in the Makefile ``run`` target).
This module re-exports the application instance created by the factory
in ``application.main`` so that the Uvicorn import path remains stable.
"""

from application.main import fastapi_application

__all__ = ["fastapi_application"]

if __name__ == "__main__":
    import uvicorn

    import application.configuration

    TIMEOUT_FOR_GRACEFUL_SHUTDOWN_IN_SECONDS = 60

    application_configuration = application.configuration.ApplicationConfiguration()

    uvicorn.run(
        "main:fastapi_application",
        host=application_configuration.application_host,
        port=application_configuration.application_port,
        reload=False,
        timeout_graceful_shutdown=TIMEOUT_FOR_GRACEFUL_SHUTDOWN_IN_SECONDS,
    )
