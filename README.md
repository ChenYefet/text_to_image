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
- **llama.cpp** — pre-built binaries available at [https://github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases)
- **A GGUF model file** — for example, [Meta-Llama-3.2-8B-Instruct](https://huggingface.co/models?search=llama-3.2) or [Mistral-7B-Instruct](https://huggingface.co/models?search=mistral-7b-instruct) quantized to GGUF format (Q4_K_M recommended for ~4.6 GB size)
- *(Recommended)* A Python virtual environment manager (`venv`, `virtualenv`, or `conda`).
- *(Recommended)* An NVIDIA GPU with CUDA support for faster image generation. CPU-only mode is supported but significantly slower.
- Approximately **14 GB of free disk space**:
  - ~4.6 GB for the GGUF language model
  - ~4 GB for Stable Diffusion model weights (downloaded automatically on first run)
  - ~2.5 GB for PyTorch
  - ~3 GB for other Python dependencies (`diffusers`, `transformers`, `accelerate`, etc.)

---

## Pre-Setup: Obtaining llama.cpp and a Model File

### Getting llama.cpp Binaries

1. Visit the [llama.cpp releases page](https://github.com/ggml-org/llama.cpp/releases)
2. Download the appropriate pre-built binary for your platform:
   - **Windows**: `llama-*-bin-win-*.zip` (choose the version matching your CPU architecture)
   - **macOS**: `llama-*-bin-macos-*.zip`
   - **Linux**: `llama-*-bin-ubuntu-*.zip`
3. Extract the archive — you'll get a folder containing `llama-server` (or `llama-server.exe` on Windows) and supporting `.dll`/`.so` files

### Getting a GGUF Model File

You need a GGUF-format language model for prompt enhancement. Recommended options:

| Model | Size (Q4_K_M) | Download Link |
|---|---|---|
| **Meta-Llama-3.2-8B-Instruct** | ~4.6 GB | [HuggingFace](https://huggingface.co/models?search=llama-3.2-8b-instruct+gguf) |
| **Meta-Llama-3-8B-Instruct** | ~4.6 GB | [HuggingFace](https://huggingface.co/models?search=llama-3-8b-instruct+gguf) |
| **Mistral-7B-Instruct-v0.3** | ~4.4 GB | [HuggingFace](https://huggingface.co/models?search=mistral-7b-instruct-v0.3+gguf) |

Look for models with `Q4_K_M` quantization (good balance of quality and size). Download the `.gguf` file to a location on your system (e.g., `C:\Models\` on Windows or `~/Models/` on macOS/Linux).

---

## Setup Instructions

### Step 1: Clone the Repository

```bash
git clone <repository_url>
cd text_to_image
```

### Step 2: Set Up llama.cpp Binaries

Create a `llama.cpp/` directory inside the project and place the extracted llama.cpp binaries there:

```bash
# Create the directory
mkdir llama.cpp

# Move/copy the extracted llama.cpp files into it
# Windows example:
# move C:\Downloads\llama-*-bin-win-*\* llama.cpp\
```

Your project structure should now include:

```
text_to_image/
├── llama.cpp/
│   ├── llama-server.exe        (Windows)
│   ├── llama-server            (macOS/Linux)
│   ├── ggml*.dll               (Windows) or *.so (Linux)
│   └── ... (other binaries)
└── ... (other project files)
```

### Step 3: Create a Python Virtual Environment

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

### Step 4: Install PyTorch

For **GPU (CUDA)** support, install PyTorch with the appropriate CUDA version from [https://pytorch.org/get-started/locally/](https://pytorch.org/get-started/locally/). For example:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

For **CPU-only** mode, the default pip install is sufficient (PyTorch will be installed as a dependency of `diffusers` in the next step).

### Step 5: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 6: Configure Environment Variables

```bash
# Linux / macOS
cp .env.example .env

# Windows (Command Prompt)
copy .env.example .env
```

Open `.env` in a text editor. The defaults are suitable for a standard local setup and typically don't require changes. Key settings:

- `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` — URL of the llama.cpp server (default: `http://localhost:8080`)
- `TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID` — HuggingFace model ID (default: `stable-diffusion-v1-5/stable-diffusion-v1-5`)
- `TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE` — `auto`, `cpu`, or `cuda` (default: `auto`)

### Step 7: Start the llama.cpp Server

**Linux / macOS:**
```bash
./llama.cpp/llama-server \
    --model ~/Models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf \
    --host 0.0.0.0 \
    --port 8080 \
    --ctx-size 2048
```

**Windows (Command Prompt):**
```cmd
llama.cpp\llama-server.exe --model C:\Models\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf --host 0.0.0.0 --port 8080 --ctx-size 2048
```

**Windows (PowerShell):**
```powershell
.\llama.cpp\llama-server.exe --model C:\Models\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf --host 0.0.0.0 --port 8080 --ctx-size 2048
```

Adjust the `--model` path to point to your downloaded GGUF model file. The server will start on port 8080 and run on CPU by default.

⏱️ **First-time startup:** The model will take 10-30 seconds to load depending on your CPU.

### Step 8: Start the Text-to-Image API Service

Open a **new terminal window** (keep the llama.cpp server running in the first), activate the virtual environment again, and run:

```bash
python main.py
```

⏱️ **First-time startup:** The Stable Diffusion model weights (~4 GB) will be downloaded automatically from HuggingFace Hub and cached locally. This can take 5-15 minutes depending on your internet connection. Subsequent starts load from cache and take only 10-30 seconds.

The service starts on `http://localhost:8000` by default. You will see log output confirming the selected device (CPU or CUDA) and successful pipeline loading.

**Expected output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
... | INFO     | application.services.image_generation_service | Loading Stable Diffusion pipeline 'stable-diffusion-v1-5/stable-diffusion-v1-5' on cuda (dtype=torch.float16) ...
... | INFO     | application.services.image_generation_service | Stable Diffusion pipeline loaded successfully.
... | INFO     | application.server_factory | Services initialised. Language model server: http://localhost:8080 | Stable Diffusion model: stable-diffusion-v1-5/stable-diffusion-v1-5
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## Quick Start (TL;DR)

Once you've completed the setup above, here's the quick workflow for subsequent sessions.

**Linux / macOS:**

```bash
# Terminal 1: Start llama.cpp server
./llama.cpp/llama-server --model ~/Models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf --host 0.0.0.0 --port 8080 --ctx-size 2048

# Terminal 2: Activate venv and start API service
source virtual_environment/bin/activate
python main.py

# Terminal 3: Test the service
curl -X POST http://localhost:8000/v1/prompts/enhance \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a cat"}'
```

**Windows (PowerShell):**

```powershell
# Terminal 1: Start llama.cpp server
.\llama.cpp\llama-server.exe --model C:\Models\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf --host 0.0.0.0 --port 8080 --ctx-size 2048

# Terminal 2: Activate venv and start API service
virtual_environment\Scripts\Activate.ps1
python main.py

# Terminal 3: Test the service
curl -X POST http://localhost:8000/v1/prompts/enhance -H "Content-Type: application/json" -d '{"prompt": "a cat"}'
```

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
├── .env                                           # Your local environment config (not in git)
├── README.md                                      # This file
├── text-to-image-spec-v3_0_0.md                   # Original project specification
├── llama.cpp/                                     # llama.cpp binaries (not in git)
│   ├── llama-server.exe (Windows) or llama-server (Linux/macOS)
│   └── ggml*.dll / *.so files
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

**Note:** The `llama.cpp/` directory and `.env` file are excluded from git (via `.gitignore`) as they contain platform-specific binaries and local configuration. You must set these up manually as described in the setup instructions above.

---

## Interactive API Documentation

Once the service is running, FastAPI automatically generates interactive documentation:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Troubleshooting

### llama.cpp server won't start

**Problem:** `llama-server` command not found or "No such file or directory"

**Solution:**
- Verify the binary is in the `llama.cpp/` directory: `ls llama.cpp/` (macOS/Linux) or `dir llama.cpp\` (Windows)
- On Windows, use `.\llama.cpp\llama-server.exe` (PowerShell) or `llama.cpp\llama-server.exe` (Command Prompt)
- On macOS/Linux, ensure the binary is executable: `chmod +x llama.cpp/llama-server`

### API service returns 502 Bad Gateway

**Problem:** The FastAPI service can't reach the llama.cpp server

**Solution:**
- Verify llama.cpp server is running: `curl http://localhost:8080/health`
- Check the llama.cpp server is listening on port 8080 (not another port)
- Verify `.env` has the correct `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL=http://localhost:8080`

### Stable Diffusion model download is stuck

**Problem:** First run hangs while downloading the model

**Solution:**
- This is normal for the first run — the model is ~4 GB and can take 5-15 minutes
- Check your internet connection
- If it fails, delete the cache and retry: `rm -rf ~/.cache/huggingface/` (Linux/macOS) or delete `C:\Users\<username>\.cache\huggingface\` (Windows)

### Image generation is very slow

**Problem:** Each image takes 5+ minutes to generate

**Solution:**
- You're likely running on CPU. This is expected behavior for CPU-only mode
- For faster generation:
  - Install CUDA-enabled PyTorch if you have an NVIDIA GPU: see [https://pytorch.org/get-started/locally/](https://pytorch.org/get-started/locally/)
  - Verify GPU is being used by checking the startup logs: should show `Device: cuda` not `Device: cpu`
- Reduce image size to `256x256` or `512x512` for faster CPU generation

### Windows: "DLL load failed" or "The specified module could not be found"

**Problem:** llama.cpp server won't start due to missing DLL files

**Solution:**
- Ensure all `.dll` files from the llama.cpp download are in the `llama.cpp/` directory
- Install Microsoft Visual C++ Redistributable: [https://aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### Port already in use

**Problem:** `Address already in use` error when starting services

**Solution:**
- Check if another process is using the port:
  - Windows: `netstat -ano | findstr :8000` or `netstat -ano | findstr :8080`
  - macOS/Linux: `lsof -i :8000` or `lsof -i :8080`
- Kill the conflicting process or change the port in `.env` (`TEXT_TO_IMAGE_APPLICATION_PORT`)

### Need help?

If you encounter issues not covered here, please:
1. Check the service logs for detailed error messages
2. Verify all prerequisites are installed
3. Ensure the `.env` file is configured correctly
4. Try the example curl commands to isolate the issue
