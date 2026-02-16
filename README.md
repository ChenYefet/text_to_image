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
| **Image Generation** | HuggingFace diffusers | In-process Stable Diffusion pipeline loaded via the `diffusers` library. Auto-detects GPU/CPU, downloads the model from HuggingFace Hub on first run, and requires no external server process. |

### Scalability Considerations

- **Asynchronous throughout** — every I/O operation uses `async`/`await`, and Stable Diffusion inference is dispatched to a thread pool to avoid blocking the event loop.
- **Connection pooling** — persistent `httpx.AsyncClient` instances reuse TCP connections across requests, reducing handshake overhead.
- **Inference serialisation** — an `asyncio.Lock` serialises concurrent image generation requests to prevent GPU memory contention.
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
                         │                               │
                         │  ┌─────────────────────────┐  │
                         │  │ Stable Diffusion        │  │
                         │  │ (diffusers, in-process) │  │
                         │  └─────────────────────────┘  │
                         └──────────────┬───────────────┘
                                        │
                            ┌───────────▼──┐
                            │  llama.cpp   │
                            │  server      │
                            │  :8080       │
                            └──────────────┘
```

The service acts as a unified gateway between the client and two backends:

1. **llama.cpp** — provides prompt enhancement via the OpenAI-compatible `/v1/chat/completions` endpoint (CPU-only, external process).
2. **Stable Diffusion** — generates images in-process using the HuggingFace `diffusers` library. The model is loaded into memory at startup and runs on GPU (CUDA) or CPU automatically.

---

## Environment Prerequisites

Before setting up this project, ensure you have the following installed:

- **Python 3.11 or later** — [https://www.python.org/downloads/](https://www.python.org/downloads/)
- **Git** — [https://git-scm.com/downloads](https://git-scm.com/downloads)
- **PyTorch** — installed via pip. For GPU acceleration, install the CUDA-enabled build (see [https://pytorch.org/get-started/locally/](https://pytorch.org/get-started/locally/)).
- **llama.cpp** — compiled from source or a pre-built binary, together with a GGUF-format model file (for example, Llama 3.2 or Mistral 7B).
- *(Recommended)* A Python virtual environment manager (`venv`, `virtualenv`, or `conda`).
- *(Recommended)* An NVIDIA GPU with CUDA support for faster image generation. CPU-only mode is supported but significantly slower.
- Approximately **4 GB of free disk space** for the Stable Diffusion model weights (downloaded automatically on first run).

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

### Step 3: Install PyTorch

For **GPU (CUDA)** support, install PyTorch with the appropriate CUDA version from [https://pytorch.org/get-started/locally/](https://pytorch.org/get-started/locally/). For example:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

For **CPU-only** mode, the default pip install is sufficient (PyTorch will be installed as a dependency of `diffusers` in the next step).

### Step 4: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` in a text editor and adjust the values to match your local environment. The defaults are suitable for a standard local setup. Key settings:

- `TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID` — HuggingFace model ID or local path (default: `stable-diffusion-v1-5/stable-diffusion-v1-5`).
- `TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE` — `auto`, `cpu`, or `cuda` (default: `auto`).

### Step 6: Start the llama.cpp Server

```bash
./llama-server \
    --model /path/to/your/model.gguf \
    --host 0.0.0.0 \
    --port 8080 \
    --ctx-size 2048
```

This starts the llama.cpp server in OpenAI-compatible mode on port 8080. Adjust the `--model` path to point to your downloaded GGUF model file. CPU-only execution is the default.

### Step 7: Start the Text-to-Image API Service

```bash
python main.py
```

On first run, the Stable Diffusion model weights (~4 GB) are downloaded automatically from HuggingFace Hub and cached locally. Subsequent starts load from cache.

The service starts on `http://localhost:8000` by default. You will see log output confirming the selected device (CPU or CUDA) and successful pipeline loading.

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
| Backend service unavailable | **502 Bad Gateway** | The llama.cpp server cannot be reached, or the Stable Diffusion pipeline encountered a runtime error. |
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
    │   └── image_generation_service.py            # Stable Diffusion pipeline (diffusers)
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
