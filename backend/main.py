"""FastAPI server bridging the frontend and Azure OpenAI Realtime API via LangGraph."""

import json
import os
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from backend.realtime_client import RealtimeClient, MODE_GA
from backend.foundry_client import FoundryRealtimeClient
from backend.agent_client import FoundryAgentClient
from backend.graph import get_tool_definitions, handle_tool_calls

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LangGraph Live Voice Demo")

# Cached region lookup result
_cached_region: str = ""

# Serve static frontend files
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


@app.get("/")
async def serve_index():
    """Serve the frontend HTML page."""
    return FileResponse(str(frontend_path / "index.html"))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    api_mode = os.getenv("REALTIME_API_MODE", MODE_GA)
    return {"status": "ok", "service": "langgraph-live-voice", "api_mode": api_mode}


@app.get("/config")
async def get_config():
    """Return current agent/connection configuration for UI display."""
    endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT", ""))
    project_name = os.getenv("FOUNDRY_PROJECT_NAME", "")
    agent_name = os.getenv("FOUNDRY_AGENT_NAME", "")

    # Try to get region by matching endpoint resource name against ARM (cached)
    global _cached_region
    region = os.getenv("AZURE_REGION", "") or _cached_region
    if not region and endpoint:
        try:
            from urllib.parse import urlparse
            from azure.identity import DefaultAzureCredential
            import requests as _requests

            host = urlparse(endpoint).hostname or ""
            resource_name = host.split(".")[0]  # e.g. "ez-aifoundry-test-ca"

            cred = DefaultAzureCredential()
            token = cred.get_token("https://management.azure.com/.default").token
            headers = {"Authorization": f"Bearer {token}"}

            # Search across subscriptions for the resource
            subs_resp = _requests.get(
                "https://management.azure.com/subscriptions?api-version=2022-12-01",
                headers=headers
            )
            for sub in subs_resp.json().get("value", []):
                sub_id = sub["subscriptionId"]
                res_resp = _requests.get(
                    f"https://management.azure.com/subscriptions/{sub_id}/providers/Microsoft.CognitiveServices/accounts?api-version=2023-05-01",
                    headers=headers
                )
                if res_resp.status_code == 200:
                    for account in res_resp.json().get("value", []):
                        if account.get("name", "").lower() == resource_name.lower():
                            region = account.get("location", "")
                            break
                if region:
                    break
            if region:
                _cached_region = region
        except Exception as e:
            logger.debug(f"Could not get resource region: {e}")

    return {
        "azure_openai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "azure_voicelive_endpoint": endpoint,
        "foundry_agent_name": agent_name,
        "foundry_project_name": project_name,
        "foundry_agent_version": os.getenv("FOUNDRY_AGENT_VERSION", ""),
        "azure_openai_deployment": os.getenv("AZURE_OPENAI_REALTIME_DEPLOYMENT", "gpt-realtime-mini"),
        "azure_region": region,
    }


@app.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint that bridges the frontend audio stream with
    Azure OpenAI Realtime API, using LangGraph for tool orchestration.

    Query params:
        client: "websocket" (raw WS, default) or "foundry" (OpenAI SDK)
    """
    await websocket.accept()

    # Determine which client mode to use from query params
    client_mode = websocket.query_params.get("client", "websocket")
    voice = websocket.query_params.get("voice", "alloy")
    turn_detection = websocket.query_params.get("turn_detection", "server_vad")
    vad_threshold = float(websocket.query_params.get("vad_threshold", "0.5"))
    silence_duration = int(websocket.query_params.get("silence_duration", "500"))
    max_tokens = websocket.query_params.get("max_tokens", "inf")
    noise_reduction = websocket.query_params.get("noise_reduction", "0") == "1"
    echo_cancellation = websocket.query_params.get("echo_cancellation", "0") == "1"

    session_options = {
        "turn_detection": turn_detection,
        "vad_threshold": vad_threshold,
        "silence_duration": silence_duration,
        "max_tokens": None if max_tokens == "inf" else int(max_tokens),
        "noise_reduction": noise_reduction,
        "echo_cancellation": echo_cancellation,
    }
    logger.info(f"Client WebSocket connected (client_mode={client_mode}, voice={voice}, options={session_options})")

    # Get Azure OpenAI configuration from environment
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.getenv("AZURE_OPENAI_REALTIME_DEPLOYMENT", "gpt-realtime-mini")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    use_entra_id = os.getenv("AZURE_USE_ENTRA_ID", "false").lower() == "true"
    api_mode = os.getenv("REALTIME_API_MODE", MODE_GA)

    if not endpoint:
        await websocket.send_json({"type": "error", "message": "AZURE_OPENAI_ENDPOINT not configured"})
        await websocket.close()
        return

    # Create the appropriate Realtime API client
    if client_mode == "agent":
        voicelive_endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT", endpoint)
        agent_name = os.getenv("FOUNDRY_AGENT_NAME", "")
        project_name = os.getenv("FOUNDRY_PROJECT_NAME", "")
        agent_version = os.getenv("FOUNDRY_AGENT_VERSION") or None
        conversation_id = os.getenv("FOUNDRY_CONVERSATION_ID") or None
        foundry_resource_override = os.getenv("FOUNDRY_RESOURCE_OVERRIDE") or None

        if not agent_name or not project_name:
            await websocket.send_json({"type": "error", "message": "FOUNDRY_AGENT_NAME and FOUNDRY_PROJECT_NAME must be configured for Agent mode"})
            await websocket.close()
            return

        realtime_client = FoundryAgentClient(
            endpoint=voicelive_endpoint,
            agent_name=agent_name,
            project_name=project_name,
            agent_version=agent_version,
            conversation_id=conversation_id,
            foundry_resource_override=foundry_resource_override,
            use_entra_id=use_entra_id,
        )
    elif client_mode == "foundry":
        voicelive_endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT", endpoint)
        voicelive_model = os.getenv("AZURE_VOICELIVE_MODEL", deployment)
        realtime_client = FoundryRealtimeClient(
            endpoint=voicelive_endpoint,
            deployment=voicelive_model,
            api_key=api_key,
            use_entra_id=use_entra_id,
        )
    else:
        realtime_client = RealtimeClient(
            endpoint=endpoint,
            deployment=deployment,
            api_key=api_key,
            use_entra_id=use_entra_id,
            api_mode=api_mode,
        )

    async def handle_realtime_message(event: dict):
        """Handle messages received from the Azure OpenAI Realtime API."""
        event_type = event.get("type", "")
        if "audio.delta" not in event_type and "audio.append" not in event_type:
            logger.info(f"Realtime event received: {event_type}")

        try:
            if event_type == "session.created":
                await websocket.send_json({
                    "type": "session.created",
                    "message": "Session established with Realtime API",
                })

            elif event_type == "session.updated":
                await websocket.send_json({
                    "type": "session.updated",
                    "message": "Session configured successfully",
                })

            elif event_type in ("response.audio.delta", "response.output_audio.delta"):
                # Forward audio chunks to the frontend
                await websocket.send_json({
                    "type": "audio.delta",
                    "audio": event.get("delta", ""),
                })

            elif event_type in ("response.audio_transcript.delta", "response.output_audio_transcript.delta"):
                # Forward transcript deltas to the frontend
                await websocket.send_json({
                    "type": "transcript.delta",
                    "delta": event.get("delta", ""),
                    "role": "assistant",
                })

            elif event_type in ("response.audio_transcript.done", "response.output_audio_transcript.done"):
                await websocket.send_json({
                    "type": "transcript.done",
                    "transcript": event.get("transcript", ""),
                    "role": "assistant",
                })

            elif event_type == "conversation.item.input_audio_transcription.completed":
                # User's speech was transcribed
                transcript_text = event.get("transcript", "") or event.get("text", "")
                logger.info(f"User transcription completed: '{transcript_text[:50]}...' (keys: {list(event.keys())})")
                await websocket.send_json({
                    "type": "transcript.done",
                    "transcript": transcript_text,
                    "role": "user",
                })

            elif event_type == "conversation.item.input_audio_transcription.delta":
                # User's speech transcription delta
                delta_text = event.get("delta", "") or event.get("text", "")
                await websocket.send_json({
                    "type": "transcript.delta",
                    "delta": delta_text,
                    "role": "user",
                })

            elif event_type == "input_audio_buffer.speech_started":
                await websocket.send_json({"type": "speech.started"})

            elif event_type == "input_audio_buffer.speech_stopped":
                await websocket.send_json({"type": "speech.stopped"})

            elif event_type == "response.function_call_arguments.done":
                # A tool call has been completed by the model - process via LangGraph
                tool_call = {
                    "name": event.get("name", ""),
                    "arguments": event.get("arguments", "{}"),
                    "call_id": event.get("call_id", ""),
                }
                logger.info(f"Tool call received: {tool_call['name']}")

                await websocket.send_json({
                    "type": "tool.calling",
                    "name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                })

                # Process through LangGraph
                results = handle_tool_calls([tool_call])

                # Send results back to Realtime API
                for result in results:
                    logger.info(f"Tool result: {result['name']} -> {result['result']}")
                    await realtime_client.send_tool_result(
                        call_id=result["call_id"],
                        result=result["result"],
                    )
                    await websocket.send_json({
                        "type": "tool.result",
                        "name": result["name"],
                        "result": result["result"],
                    })

            elif event_type == "response.done":
                await websocket.send_json({"type": "response.done"})

            elif event_type == "error":
                error_info = event.get("error", {})
                logger.error(f"Realtime API error: {error_info}")
                await websocket.send_json({
                    "type": "error",
                    "message": error_info.get("message", "Unknown error"),
                })

        except WebSocketDisconnect:
            logger.info("Client disconnected during message handling")
        except Exception as e:
            logger.error(f"Error handling realtime message: {e}")

    try:
        # Connect to Azure OpenAI Realtime API
        await realtime_client.connect(on_message=handle_realtime_message)
    except ValueError as e:
        # Agent validation failed (e.g., agent not found)
        logger.error(f"Connection failed: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close()
        return
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        await websocket.send_json({"type": "error", "message": f"Failed to connect: {e}"})
        await websocket.close()
        return

    try:
        # Configure the session with LangGraph tools
        tools = get_tool_definitions()
        await realtime_client.configure_session(tools=tools, voice=voice, **session_options)

        # Forward messages from client to Realtime API
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type", "")

            if msg_type == "audio.append":
                # Forward audio from client to Realtime API
                await realtime_client.send_audio(message.get("audio", ""))

            elif msg_type == "audio.commit":
                # Client manually commits audio (push-to-talk mode)
                await realtime_client.commit_audio()

            elif msg_type == "response.cancel":
                await realtime_client.cancel_response()

            elif msg_type == "session.update":
                # Update session config with new options from client
                updated_options = {
                    "turn_detection": message.get("turn_detection", session_options.get("turn_detection")),
                    "vad_threshold": message.get("vad_threshold", session_options.get("vad_threshold")),
                    "silence_duration": message.get("silence_duration", session_options.get("silence_duration")),
                    "noise_reduction": message.get("noise_reduction", session_options.get("noise_reduction")),
                    "echo_cancellation": message.get("echo_cancellation", session_options.get("echo_cancellation")),
                }
                session_options.update(updated_options)
                updated_voice = message.get("voice", voice)
                await realtime_client.configure_session(
                    tools=tools,
                    instructions=message.get("instructions", ""),
                    voice=updated_voice,
                    **session_options,
                )
                logger.info(f"Session updated: voice={updated_voice}, options={session_options}")

    except WebSocketDisconnect:
        logger.info("Client WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await realtime_client.disconnect()
        logger.info("Cleaned up Realtime API connection")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
