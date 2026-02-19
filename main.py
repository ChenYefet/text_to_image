"""
Entry point for the Text-to-Image with Prompt Assist service.

This module creates the FastAPI application instance and starts the Uvicorn
ASGI server when executed directly.
"""

import uvicorn

import application.server_factory

fastapi_application = application.server_factory.create_application()

if __name__ == "__main__":
    import configuration

    application_configuration = configuration.ApplicationConfiguration()

    uvicorn.run(
        "main:fastapi_application",
        host=application_configuration.application_host,
        port=application_configuration.application_port,
        reload=False,
        timeout_graceful_shutdown=60,
    )
