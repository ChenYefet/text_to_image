"""
Entry point for the Text-to-Image with Prompt Assist service.

This module creates the FastAPI application instance and starts the Uvicorn
ASGI server when executed directly.
"""

import logging

import uvicorn

import application.server_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

fastapi_application = application.server_factory.create_application()

if __name__ == "__main__":
    import configuration

    application_configuration = configuration.ApplicationConfiguration()

    uvicorn.run(
        "main:fastapi_application",
        host=application_configuration.application_host,
        port=application_configuration.application_port,
        reload=True,
    )
