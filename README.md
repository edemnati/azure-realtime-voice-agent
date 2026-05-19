# Azure Realtime Voice Agent — Dual-Mode Demo

A production-ready sample demonstrating two approaches to building **real-time voice agents** on Azure, served through a single web application:

| Mode | SDK | Tool Calling | Best For |
|------|-----|:------------:|----------|
| **Raw WebSocket** | `websockets` + direct Azure OpenAI Realtime API | ✅ Full LangGraph support | Custom orchestration, function calling, agentic workflows |
| **Voice Live SDK** | `azure-ai-voicelive` | ✅ LangGraph support | Managed voice experience, echo cancellation, noise reduction |

---

## Architecture

```
┌─────────────────┐         WebSocket          ┌──────────────────────┐
│   Browser        │ ◄───────────────────────── │   FastAPI Server      │
│   (24kHz PCM16)  │ ────────────────────────► │                      │
└─────────────────┘     audio / events          └──────────┬───────────┘
                                                           │
                            ┌───────────────────────────────┼────────────────────────────┐
                            │                               │                            │
                   ┌────────▼─────────┐          ┌─────────▼──────────┐       ┌──────────▼──────────┐
                   │  RealtimeClient   │          │ FoundryRealtimeClient│       │  LangGraph Agent    │
                   │  (Raw WebSocket)  │          │ (Voice Live SDK)    │       │  (Tool Orchestration)│
                   └────────┬──────────┘          └─────────┬──────────┘       └─────────────────────┘
                            │                               │                            │
                            ▼                               ▼                   Tools: time, weather, KB
                ┌───────────────────────┐     ┌──────────────────────────┐
                │ Azure OpenAI          │     │ Azure Voice Live API      │
                │ Realtime API (GA)     │     │ (Managed, echo/noise)     │
                │ wss://...openai.azure │     │ services.ai.azure.com     │
                └───────────────────────┘     └──────────────────────────┘
```

---

## Features

### Raw WebSocket Mode (OpenAI Realtime API)
- Direct WebSocket connection to Azure OpenAI Realtime API (GA endpoint)
- **LangGraph tool orchestration** — function calling for weather, time, knowledge base
- Supports GA models (`gpt-realtime-mini`, `gpt-realtime`, `gpt-realtime-1.5`)
- Server-side VAD with configurable threshold and silence duration
- Input audio transcription via Whisper
- OpenAI voices (alloy, echo, shimmer, etc.)
- Speech interruption handling

### Voice Live SDK Mode (Azure Foundry)
- Managed connection via the official `azure-ai-voicelive` Python SDK
- **LangGraph tool orchestration** — function calling for weather, time, knowledge base
- Supports GA models (`gpt-realtime-mini`, `gpt-realtime`, `gpt-realtime-1.5`)
- Server-side VAD + Azure Semantic VAD (AI-powered turn detection)
- Built-in echo cancellation and noise reduction
- Azure neural voices (e.g., `en-US-Ava:DragonHDLatestNeural`) + OpenAI voices
- Automatic speech interruption handling

### Shared
- **Web-based UI** with client mode toggle (switch before connecting)
- Live audio visualizer
- Real-time transcript panel (user + assistant)
- Tool activity panel showing function calls and results
- Settings panel for dynamic instruction updates
- Microsoft Entra ID authentication (recommended) or API key

---

## Prerequisites

1. **Python 3.10+**
2. **Azure OpenAI Resource** with a deployed realtime model
   - For WebSocket mode: deploy `gpt-realtime-mini` (or `gpt-realtime`, `gpt-realtime-1.5`)
   - Supported regions: East US 2, Sweden Central
3. **Microsoft Foundry resource** (for Voice Live mode)
   - Endpoint format: `https://<resource>.services.ai.azure.com/`
   - No model deployment needed — Voice Live is fully managed
4. **Azure CLI** (`az login`) for Entra ID authentication
5. **Role Assignment**: `Cognitive Services User` on the resource
6. **Browser** with microphone access (Chrome/Edge recommended)

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/edemnati/azure-realtime-voice-agent.git
cd azure-realtime-voice-agent
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your resource values:

```env
# Raw WebSocket mode
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_REALTIME_DEPLOYMENT=gpt-realtime-mini
AZURE_USE_ENTRA_ID=true
REALTIME_API_MODE=ga

# Voice Live SDK mode
AZURE_VOICELIVE_ENDPOINT=https://your-resource.services.ai.azure.com/
AZURE_VOICELIVE_MODEL=gpt-realtime-mini
```

### 3. Authenticate

```bash
az login
```

### 4. Run

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Open

Navigate to [http://localhost:8000](http://localhost:8000)

---

## Docker

### Build

```bash
docker build -t azure-realtime-voice-agent .
```

### Run

```bash
docker run -p 8000:8000 \
  -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com \
  -e AZURE_OPENAI_REALTIME_DEPLOYMENT=gpt-realtime-mini \
  -e AZURE_USE_ENTRA_ID=false \
  -e AZURE_OPENAI_API_KEY=your-api-key \
  -e AZURE_VOICELIVE_ENDPOINT=https://your-resource.services.ai.azure.com/ \
  -e AZURE_VOICELIVE_MODEL=gpt-realtime-mini \
  -e REALTIME_API_MODE=ga \
  azure-realtime-voice-agent
```

Or use an env file:

```bash
docker run -p 8000:8000 --env-file .env azure-realtime-voice-agent
```

> **Note:** For Entra ID authentication inside a container, mount Azure CLI credentials or use a managed identity when deploying to Azure (e.g., Azure Container Apps).

---

## Usage

1. Select **Client Mode** from the dropdown:
   - *Raw WebSocket* — full tool calling support via LangGraph
   - *Voice Live SDK* — managed audio with echo cancellation
2. Click **Connect** to establish the audio session
3. Grant microphone permission when prompted
4. **Speak naturally** — server-side VAD handles turn-taking
5. Try asking:
   - "What time is it?" (tool call)
   - "What's the weather in Tokyo?" (tool call)
   - "Tell me about the company" (knowledge base search)
   - Or just have a conversation!

---

## Session Options

The right panel exposes real-time session configuration. Options are sent as query parameters when connecting.

### Turn Detection

| Option | Description | Values |
|--------|-------------|--------|
| **Mode** | How the server detects when you stop speaking to trigger a response. | `Server VAD` — uses audio energy levels to detect speech boundaries. `Azure Semantic VAD` (Foundry only) — AI-powered detection that understands pauses in context (e.g. thinking vs. finished). |
| **Threshold** | Sensitivity of speech detection. Higher values require louder speech to trigger. | `0.0` (very sensitive) to `1.0` (requires loud speech). Default: `0.5` |
| **Silence Duration** | How long to wait after you stop speaking before generating a response. | `200ms` (fast/interrupts easily) to `2000ms` (patient). Default: `500ms` |

### Model

| Option | Description | Values |
|--------|-------------|--------|
| **Temperature** | Controls randomness. Lower = focused/deterministic. Higher = creative/varied. | `0.6` to `1.2`. Default: `0.8` |
| **Max Tokens** | Limits the length of each response. Shorter = faster, more concise. | `Unlimited`, `Short (~150)`, `Medium (~500)`, `Long (~1000)` |

### Audio Processing (Foundry only)

| Option | Description |
|--------|-------------|
| **Noise Reduction** | Removes background noise (keyboard, fan, traffic) from your mic input before sending to the model. |
| **Echo Cancellation** | Prevents the model from hearing its own audio output through your speakers, avoiding feedback loops. |

> **Note:** Audio Processing options are only available in Voice Live SDK mode. They are disabled when using Raw WebSocket mode.

---

## Project Structure

```
azure-realtime-voice-agent/
├── backend/
│   ├── __init__.py
│   ├── main.py                # FastAPI server, WebSocket bridge, client routing
│   ├── realtime_client.py     # Raw WebSocket client (Azure OpenAI Realtime API)
│   ├── foundry_client.py      # Voice Live SDK client (azure-ai-voicelive)
│   ├── graph.py               # LangGraph state machine for tool orchestration
│   └── tools.py               # Tool definitions and implementations
├── frontend/
│   ├── index.html             # Web page with mode toggle
│   ├── app.js                 # Audio capture, WebSocket comm, playback
│   └── styles.css             # UI styling
├── .dockerignore              # Files excluded from Docker build context
├── .env.example               # Environment variable template
├── .env                       # Your local configuration (git-ignored)
├── .gitignore                 # Git ignore rules
├── Dockerfile                 # Container build definition
├── documentation.html         # Azure Voice APIs reference doc (static, not served)
├── requirements.txt           # Python dependencies
└── README.md
```

---

## How It Works

### Audio Pipeline
1. Browser captures microphone at **24kHz mono PCM16** via `ScriptProcessorNode`
2. Audio is base64-encoded and sent to FastAPI backend over WebSocket
3. Backend forwards to the selected API client
4. API returns audio response chunks (base64 PCM16)
5. Browser decodes and plays back via Web Audio API

### Client Abstraction
Both `RealtimeClient` and `FoundryRealtimeClient` implement the same interface:
- `connect(on_message)` — establish connection
- `configure_session(tools, instructions)` — set up the session
- `send_audio(base64_data)` — stream audio input
- `commit_audio()` — manual turn commit (optional)
- `send_tool_result(call_id, result)` — return tool output
- `cancel_response()` — interrupt current response
- `disconnect()` — clean up

This allows `main.py` to be client-agnostic — switching modes is transparent.

### LangGraph Tool Orchestration (Both modes)
When the Realtime API (or Voice Live SDK) emits `response.function_call_arguments.done`, the backend:
1. Routes the call through the LangGraph `StateGraph`
2. Executes the appropriate tool function
3. Returns the result to the Realtime API
4. The model generates a spoken response incorporating the tool output

---

## Supported Models

| Model | Mode | API Format |
|-------|------|-----------|
| `gpt-realtime-mini` | GA | Nested audio config |
| `gpt-realtime` | GA | Nested audio config |
| `gpt-realtime-1.5` | GA | Nested audio config |

Set `REALTIME_API_MODE=ga` in your `.env` file.

---

## Extending the Demo

### Adding Custom Tools
Edit `backend/tools.py`:
1. Add a function implementation
2. Add its definition to `TOOL_DEFINITIONS`
3. Register in `TOOL_IMPLEMENTATIONS`

The tool will automatically be available in the next session.

### Using Azure Neural Voices (Voice Live only)
In `backend/foundry_client.py`, change the `voice` parameter:
```python
voice="en-US-Ava:DragonHDLatestNeural"  # Azure neural voice
```

---

## Test Questions

Use these prompts to verify the voice agent is working correctly across both modes.

### Tool Calling (Both modes)

| # | Question | Expected Behavior |
|---|----------|-------------------|
| 1 | "What time is it?" | Triggers `get_current_time` tool, responds with current date/time |
| 2 | "What's the weather in Paris?" | Triggers `get_weather(location="Paris")` → "20°C, Overcast" |
| 3 | "How's the weather in Tokyo?" | Triggers `get_weather(location="Tokyo")` → "28°C, Sunny" |
| 4 | "What's the weather like in New York?" | Triggers `get_weather(location="New York")` → "72°F, Partly Cloudy" |
| 5 | "Tell me about the company" | Triggers `search_knowledge_base(query="company")` → Contoso Ltd info |
| 6 | "What products do you offer?" | Triggers `search_knowledge_base(query="product")` → Contoso AI Assistant |
| 7 | "How do I contact support?" | Triggers `search_knowledge_base(query="support")` → support@contoso.com |
| 8 | "What time is it and what's the weather in London?" | Chains `get_current_time` + `get_weather(location="London")` |
| 9 | "What's the weather in Berlin?" | Triggers `get_weather(location="Berlin")` → "Unknown location" (not in data) |

### Conversation (Both modes)

| # | Question | Expected Behavior |
|---|----------|-------------------|
| 1 | "Hello, how are you?" | Natural conversational response, no tool call |
| 2 | "Explain quantum computing in simple terms" | Longer response, tests streaming audio |
| 3 | "Count from 1 to 10 slowly" | Tests sustained audio output |
| 4 | "Can you speak faster?" | Tests instruction following |
| 5 | "Repeat after me: the quick brown fox jumps over the lazy dog" | Tests audio input transcription accuracy |
| 6 | "What is 25 times 17?" | Tests reasoning without tools |

### Voice & Audio Quality (Voice Live SDK mode)

| # | Action | Expected Behavior |
|---|--------|-------------------|
| 1 | Say something while typing on keyboard | Noise reduction filters keyboard sounds |
| 2 | Play music from speakers while talking | Echo cancellation prevents feedback loop |
| 3 | Interrupt the assistant mid-sentence | Speech interruption halts current response |
| 4 | Stay silent for 3 seconds after speaking | VAD detects end of turn, generates response |
| 5 | Speak very softly with threshold at 0.5 | Should still detect speech |

### Session Options

| # | Action | Expected Behavior |
|---|--------|-------------------|
| 1 | Change instructions to "Respond only in French" then ask "What time is it?" | Response in French |
| 2 | Change instructions to "Be extremely brief, one sentence max" | Short responses |
| 3 | Adjust VAD threshold to 0.9 and speak softly | May not detect speech |
| 4 | Set silence duration to 2000ms | Longer pause before response |
| 5 | Change voice to "Shimmer" and ask a question | Different voice on response |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No audio from assistant | Check browser console for decode errors. Ensure 24kHz PCM16 format. |
| Connection refused | Verify `.env` endpoint and that `az login` is current. |
| 401 Unauthorized | Confirm `Cognitive Services User` role on the resource. |
| "Voice Live SDK mode" fails | Ensure `AZURE_VOICELIVE_ENDPOINT` uses `.services.ai.azure.com` format. |
| Tools not working | Ensure you're speaking clearly and the tool-triggering question is specific (e.g., "What time is it?"). |
| Echo/feedback | Use headphones, or switch to Voice Live mode (built-in echo cancellation). |

---

## References

- [Azure OpenAI Realtime API](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/realtime-audio)
- [Azure Voice Live Quickstart](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-quickstart)
- [Voice Live SDK (PyPI)](https://pypi.org/project/azure-ai-voicelive/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)

---

## License

MIT
