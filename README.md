# Text-to-Image with Prompt Assist

A production-grade REST API service that generates images from text prompts
using Stable Diffusion, with optional AI-powered prompt enhancement via a
llama.cpp language model.

---

## Technology Stack

| Component | Technology | Justification |
|---|---|---|
| **Backend Language** | Python 3.11+ | Mature async/await ecosystem, comprehensive type annotation support, and wide availability of machine learning and HTTP libraries. Python's readability directly supports the self-documenting code requirement. |
| **HTTP Framework** | FastAPI | Native async support, automatic OpenAPI/Swagger documentation generation, and deep integration with Pydantic for declarative request validation. Built on Starlette and Uvicorn for high-throughput I/O-bound workloads. |
| **ASGI Server** | Uvicorn | Production-ready ASGI server with hot-reload capability during development and support for multiple worker processes in production deployments. |
| **JSON Validation** | Pydantic v2 | Declarative, self-documenting validation models with built-in serialisation support. Validation rules are expressed as class definitions rather than imperative logic. |
| **HTTP Client** | httpx | Async-native HTTP client with comprehensive timeout configuration, connection pooling, and structured error handling for service-to-service communication. |
| **Language Model** | llama.cpp (OpenAI-compatible mode) | Lightweight, CPU-only inference server that exposes an OpenAI-compatible `/v1/chat/completions` endpoint. No GPU required. |
| **Image Generation** | AUTOMATIC1111 Stable Diffusion Web UI | Well-documented REST API (`/sdapi/v1/txt2img`) for local text-to-image generation with extensive model and sampler support. |

### Scalability Considerations

- **Asynchronous throughout** — every I/O operation uses `async`/`await`, ensuring the event loop is never blocked by network calls to downstream services.
- **Connection pooling** — persistent `httpx.AsyncClient` instances reuse TCP connections across requests, reducing handshake overhead.
- **Stateless service** — no in-process state is shared between requests, allowing horizontal scaling behind a load balancer.
- **Environment-based configuration** — all settings are loaded from environment variables (12-factor app compliant), enabling deployment across development, staging, and production environments without code changes.
- **Factory pattern** — the application is constructed via a factory function, making it straightforward to create isolated instances for testing or multi-worker deployments.

---

## Architecture Overview

```
                         ┌──────────────────────────────┐
                         │       Client (curl)           │
                         └──────────────┬───────────────┘
                                        │
                                   HTTP requests
                                        │
                         ┌──────────────▼───────────────┐
                         │  Text-to-Image API Service    │
                         │  (FastAPI on Uvicorn)         │
                         │  http://localhost:8000         │
                         └──────┬───────────────┬───────┘
                                │               │
                    ┌───────────▼──┐     ┌──────▼──────────┐
                    │  llama.cpp   │     │ Stable Diffusion │
                    │  server      │     │ Web UI           │
                    │  :8080       │     │ :7860            │
                    └──────────────┘     └─────────────────┘
```

The service acts as a unified gateway between the client and two backend services:

1. **llama.cpp** — provides prompt enhancement via the OpenAI-compatible `/v1/chat/completions` endpoint (CPU-only).
2. **Stable Diffusion Web UI** — generates images via the `/sdapi/v1/txt2img` endpoint.

---

## Environment Prerequisites

Before setting up this project, ensure you have the following installed:

- **Python 3.11 or later** — [https://www.python.org/downloads/](https://www.python.org/downloads/)
- **Git** — [https://git-scm.com/downloads](https://git-scm.com/downloads)
- **llama.cpp** — compiled from source or a pre-built binary, together with a GGUF-format model file (for example, Llama 3.2 or Mistral 7B).
- **AUTOMATIC1111 Stable Diffusion Web UI** — [https://github.com/AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui), with at least one Stable Diffusion checkpoint model downloaded.
- *(Recommended)* A Python virtual environment manager (`venv`, `virtualenv`, or `conda`).

---

## Setup Instructions

### Step 1: Clone the Repository

```bash
git clone <repository_url>
cd text_to_image
```

### Step 2: Create a Python Virtual Environment

```bash
python -m venv virtual_environment
```

Activate the virtual environment:

```bash
# Linux / macOS
source virtual_environment/bin/activate

# Windows (Command Prompt)
virtual_environment\Scripts\activate

# Windows (PowerShell)
virtual_environment\Scripts\Activate.ps1
```

### Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` in a text editor and adjust the values to match your local environment. The defaults are suitable for a standard local setup.

### Step 5: Start the llama.cpp Server

```bash
./llama-server \
    --model /path/to/your/model.gguf \
    --host 0.0.0.0 \
    --port 8080 \
    --ctx-size 2048
```

This starts the llama.cpp server in OpenAI-compatible mode on port 8080. Adjust the `--model` path to point to your downloaded GGUF model file. CPU-only execution is the default.

### Step 6: Start the Stable Diffusion Web UI

```bash
cd /path/to/stable-diffusion-webui
python launch.py --api --listen
```

The `--api` flag enables the REST API. The `--listen` flag allows connections from other processes on the same machine. By default, the Web UI starts on port 7860.

### Step 7: Start the Text-to-Image API Service

```bash
python main.py
```

The service starts on `http://localhost:8000` by default. You will see log output confirming that both backend services have been initialised.

---

## API Endpoints

### POST /v1/prompts/enhance

Enhances a raw text prompt using the language model.

**Request body:**

```json
{
    "prompt": "A cat sitting on a windowsill"
}
```

**Response body (200 OK):**

```json
{
    "enhanced_prompt": "A fluffy ginger tabby cat sitting gracefully on a sunlit Victorian windowsill, soft golden-hour lighting streaming through lace curtains, warm colour palette with amber and cream tones, photorealistic style with shallow depth of field"
}
```

### POST /v1/images/generations

Generates one or more images from a text prompt.

**Request body:**

```json
{
    "prompt": "A sunset over a mountain range with vivid colours",
    "use_enhancer": true,
    "n": 1,
    "size": "512x512"
}
```

**Response body (200 OK):**

```json
{
    "created_at_unix_timestamp": 1700000000,
    "data": [
        {
            "base64_encoded_image": "iVBORw0KGgoAAAANSUhEUgAA...",
            "content_type": "image/png"
        }
    ]
}
```

**Request body fields:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `prompt` | string | Yes | — | The text prompt describing the desired image (1–4 096 characters). |
| `use_enhancer` | boolean | No | `false` | When `true`, the prompt is enhanced by the language model before generation. |
| `n` | integer | No | `1` | Number of images to generate (1–4). |
| `size` | string | No | `"512x512"` | Image dimensions. Supported: `256x256`, `512x512`, `768x768`, `1024x1024`. |

---

## Error Handling

All error responses follow a consistent JSON structure:

```json
{
    "error": "A human-readable description of what went wrong.",
    "status_code": 400
}
```

| Condition | HTTP Status | Description |
|---|---|---|
| Invalid JSON or validation failure | **400 Bad Request** | The request body contains malformed JSON, missing required fields, or values that fail validation. |
| Backend service unavailable | **502 Bad Gateway** | The llama.cpp or Stable Diffusion server cannot be reached, returned an error, or timed out. |
| Unexpected internal error | **500 Internal Server Error** | An unhandled exception occurred within the service. |

---

## Example curl Commands

### 1. Enhance a Prompt

```bash
curl -X POST http://localhost:8000/v1/prompts/enhance \
    -H "Content-Type: application/json" \
    -d '{"prompt": "A cat sitting on a windowsill"}'
```

### 2. Generate an Image Without Enhancement

```bash
curl -X POST http://localhost:8000/v1/images/generations \
    -H "Content-Type: application/json" \
    -d '{"prompt": "A sunset over a mountain range with vivid colours", "use_enhancer": false, "n": 1, "size": "512x512"}'
```

### 3. Generate Two Images With Prompt Enhancement

```bash
curl -X POST http://localhost:8000/v1/images/generations \
    -H "Content-Type: application/json" \
    -d '{"prompt": "A dog playing in a park", "use_enhancer": true, "n": 2, "size": "512x512"}'
```

---

## Project Structure

```
text_to_image/
├── main.py                                        # Application entry point
├── configuration.py                               # Environment-based configuration
├── requirements.txt                               # Python dependencies
├── .env.example                                   # Example environment variables
├── README.md                                      # This file
└── application/
    ├── __init__.py
    ├── server_factory.py                          # FastAPI application factory
    ├── dependencies.py                            # Dependency injection providers
    ├── models.py                                  # Request and response Pydantic models
    ├── exceptions.py                              # Custom exception classes
    ├── error_handling.py                          # Centralised error handler registration
    ├── services/
    │   ├── __init__.py
    │   ├── language_model_service.py              # llama.cpp integration
    │   └── image_generation_service.py            # Stable Diffusion integration
    └── routes/
        ├── __init__.py
        ├── prompt_enhancement_routes.py           # POST /v1/prompts/enhance
        └── image_generation_routes.py             # POST /v1/images/generations
```

---

## Interactive API Documentation

Once the service is running, FastAPI automatically generates interactive documentation:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
