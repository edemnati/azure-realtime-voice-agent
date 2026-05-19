# Azure Live Voice Agent — Solution Comparison

Three approaches to build real-time voice AI agents on Azure. This guide helps you choose the right one for your use case.

---

## Solutions Overview

### ⚡ Option 1: Raw WebSocket

Direct WebSocket connection to the Azure OpenAI Realtime API. You control everything — audio encoding, session management, tool orchestration, and turn detection. Maximum flexibility at the cost of more code.

**Advantages:**
- Lowest latency — no intermediary services
- Full control over audio pipeline and session lifecycle
- Works with any OpenAI Realtime-compatible endpoint
- Custom tool orchestration via LangGraph
- Supports both API key and Entra ID authentication
- Simplest dependency footprint (GA SDK)

**Limitations:**
- No built-in noise reduction or echo cancellation
- No Azure Semantic VAD — only energy-based VAD
- You must handle audio format conversion yourself
- No interim response generation during tool calls
- Reconnection and session recovery is your responsibility
- No built-in voice configuration management

---

### 🔊 Option 2: Voice Live SDK

Azure Voice Live SDK (`azure-ai-voicelive`) manages the audio pipeline — including noise reduction, echo cancellation, and Semantic VAD — while you still control tools and instructions client-side.

**Advantages:**
- Built-in noise reduction (Azure Deep Noise Suppression)
- Built-in echo cancellation (no headphones needed)
- Azure Semantic VAD — AI-powered end-of-utterance detection
- Managed audio encoding/decoding
- Custom tool orchestration via LangGraph still available
- Configurable session options (voice, temperature, etc.)

**Limitations:**
- Slightly higher latency (audio routed through Foundry)
- Requires Entra ID — no API key authentication
- Tools/instructions managed client-side (no centralized config)
- No interim response between tool calls
- SDK is in preview (`1.2.0b5`)
- Requires Azure AI Foundry project

---

### 🤖 Option 3: Foundry Agent

A Foundry Agent with Voice Live configuration. The agent manages its own tools, instructions, and voice settings server-side. Your client just connects — everything is controlled centrally in the Foundry portal.

**Advantages:**
- Fully managed — tools, instructions & voice config in Foundry
- Interim response fills latency gaps during tool execution
- Multilingual end-of-utterance detection
- All Voice Live audio features (noise, echo, Semantic VAD)
- Versioned agents — rollback safely via `create_version`
- Centralized management — update agent without redeploying code
- Thin client — minimal backend code needed

**Limitations:**
- Highest latency — extra hop through agent orchestration
- Less control over tool execution flow
- Requires pre-creating the agent (script or portal)
- Agent SDK in preview (`azure-ai-projects 2.1.0`)
- Requires Entra ID authentication
- Voice config stored as chunked metadata (4KB limit per key)
- Limited visibility into tool execution details

---

## Feature Comparison

| Feature | Raw WebSocket | Voice Live SDK | Foundry Agent |
|---------|:---:|:---:|:---:|
| **Noise Reduction** | ✗ Manual | ✓ Built-in | ✓ Built-in |
| **Echo Cancellation** | ✗ Manual | ✓ Built-in | ✓ Built-in |
| **Turn Detection** | Energy VAD only | Energy + Semantic VAD | Energy + Semantic VAD + Multilingual EOU |
| **Interim Response** | ✗ | ✗ | ✓ LLM-generated filler |
| **Tool Orchestration** | LangGraph (client-side) | LangGraph (client-side) | Foundry (server-side) |
| **Instructions Management** | Code / session config | Code / session config | Foundry portal / metadata |
| **Authentication** | API Key or Entra ID | Entra ID only | Entra ID only |
| **Latency** | ★★★ Lowest | ★★☆ Medium | ★☆☆ Higher |
| **Client Complexity** | ★★★ High | ★★☆ Medium | ★☆☆ Low |
| **Voice Selection** | Session parameter | Session parameter | Agent metadata |
| **Azure Neural Voices** | ✗ | ✓ | ✓ |
| **Agent Versioning** | ✗ | ✗ | ✓ create_version API |
| **Update Without Redeploy** | ✗ | ✗ | ✓ Change in portal |
| **Audio Format** | PCM16 24kHz (manual) | Managed by SDK | Managed by SDK |
| **SDK Stability** | GA | Preview | Preview |

---

## Architecture

### ⚡ Raw WebSocket

```
Browser (mic) ──WebSocket──► FastAPI Backend
                                    │
                              LangGraph (tools)
                                    │
                            WebSocket connection
                                    │
                                    ▼
                     Azure OpenAI Realtime API
                        (gpt-realtime-mini)
                                    │
                                    ▼
                          Audio response ──► Browser
```

### 🔊 Voice Live SDK

```
Browser (mic) ──WebSocket──► FastAPI Backend
                                    │
                              LangGraph (tools)
                                    │
                           Voice Live SDK client
                                    │
                                    ▼
                       Azure AI Foundry Service
                     ┌─────────────────────────┐
                     │  Noise Reduction         │
                     │  Echo Cancellation       │
                     │  Semantic VAD            │
                     │  Audio Format Mgmt       │
                     └──────────┬──────────────┘
                                ▼
                     Azure OpenAI Realtime API
                                │
                                ▼
                      Audio response ──► Browser
```

### 🤖 Foundry Agent

```
Browser (mic) ──WebSocket──► FastAPI Backend
                                    │
                          Voice Live SDK client
                          (thin — no LangGraph)
                                    │
                                    ▼
                       Azure AI Foundry Service
                     ┌─────────────────────────┐
                     │  Agent Orchestration     │
                     │  ├─ Instructions         │
                     │  ├─ Tools (server-side)  │
                     │  ├─ Interim Response     │
                     │  └─ Voice Config         │
                     │                          │
                     │  Audio Processing        │
                     │  ├─ Noise Reduction      │
                     │  ├─ Echo Cancellation    │
                     │  └─ Semantic VAD + EOU   │
                     └──────────┬──────────────┘
                                ▼
                     Azure OpenAI Realtime API
                                │
                                ▼
                      Audio response ──► Browser
```

---

## Which Solution Should You Choose?

### 🧪 Prototyping & Experimentation
You want to quickly test real-time voice with minimal setup. You need API key auth, don't need audio processing, and want the lowest possible latency.

> **→ Raw WebSocket**

### 🎧 High Audio Quality Required
Your users are in noisy environments (office, car, street). You need echo cancellation for speaker mode. You still want custom tool logic in your backend.

> **→ Voice Live SDK**

### 🏢 Production Multi-Agent System
You're deploying multiple agents with different personalities, tools, and configs. You want to update behavior without code changes. You need versioning and rollback.

> **→ Foundry Agent**

### 🔧 Custom Tool Orchestration
You need complex tool chains, conditional routing, or multi-step workflows (e.g., LangGraph state machines). Tool execution must happen in your infrastructure.

> **→ Raw WebSocket or Voice Live SDK**

### 🌍 Multilingual Support
Your agent must handle multiple languages with proper end-of-utterance detection (pauses differ across languages). You need language-aware VAD.

> **→ Foundry Agent**

### ⚡ Latency-Sensitive Application
Every millisecond counts — gaming, trading, real-time translation. You can't afford the extra hop through Foundry services.

> **→ Raw WebSocket**

---

## Recommended Migration Path

| Stage | Solution | Why |
|-------|----------|-----|
| 1. Prototype | **Raw WebSocket** | Fast to set up, API key auth, test tool calling logic with LangGraph |
| 2. Audio Quality | **Voice Live SDK** | Add noise reduction & echo cancellation. Keep your LangGraph tools unchanged. |
| 3. Production | **Foundry Agent** | Centralize config, enable versioning, add interim response, thin out your backend. |

---

## Environment Variables by Mode

| Variable | Raw WebSocket | Voice Live SDK | Foundry Agent |
|----------|:---:|:---:|:---:|
| `AZURE_OPENAI_ENDPOINT` | **Required** | — | — |
| `AZURE_OPENAI_REALTIME_DEPLOYMENT` | **Required** | — | — |
| `AZURE_OPENAI_API_KEY` | Optional | — | — |
| `AZURE_VOICELIVE_ENDPOINT` | — | **Required** | — |
| `AZURE_VOICELIVE_MODEL` | — | **Required** | — |
| `PROJECT_ENDPOINT` | — | — | **Required** |
| `FOUNDRY_AGENT_NAME` | — | — | **Required** |
| `FOUNDRY_PROJECT_NAME` | — | — | **Required** |
| `FOUNDRY_AGENT_MODEL` | — | — | **Required** |
| `AZURE_USE_ENTRA_ID` | Optional | Always true | Always true |

---

## References

- [Azure OpenAI Realtime API](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/realtime-audio)
- [Azure Voice Live Quickstart](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-quickstart)
- [Voice Live SDK (PyPI)](https://pypi.org/project/azure-ai-voicelive/)
- [Azure AI Foundry Agents](https://learn.microsoft.com/en-us/azure/ai-services/agents/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
