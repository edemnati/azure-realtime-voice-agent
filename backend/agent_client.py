"""Azure Voice Live client in Foundry Agent mode.

This client connects to Voice Live with a pre-configured Foundry Agent.
The agent manages its own instructions, tools, and configuration server-side,
so no LangGraph tool orchestration is needed on the client.
"""

import asyncio
import base64
import logging
from typing import Callable, Optional, Union

from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.ai.projects import AIProjectClient

from azure.ai.voicelive.aio import connect, AgentSessionConfig
from azure.ai.voicelive.models import (
    ServerEventType,
)

logger = logging.getLogger(__name__)


class FoundryAgentClient:
    """Client using Voice Live SDK in Foundry Agent mode.

    The agent's instructions, tools, and voice config are managed server-side.
    This client handles audio streaming and event normalization for the web frontend.
    """

    def __init__(
        self,
        endpoint: str,
        agent_name: str,
        project_name: str,
        agent_version: Optional[str] = None,
        conversation_id: Optional[str] = None,
        foundry_resource_override: Optional[str] = None,
        use_entra_id: bool = True,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.agent_name = agent_name
        self.project_name = project_name
        self.agent_version = agent_version
        self.conversation_id = conversation_id
        self.foundry_resource_override = foundry_resource_override
        self.use_entra_id = use_entra_id
        self._connection = None
        self._connection_cm = None
        self._receive_task: Optional[asyncio.Task] = None
        self._on_message: Optional[Callable] = None
        self._active_response = False

    def _get_credential(self) -> AsyncTokenCredential:
        """Get credential. Agent mode requires Entra ID."""
        return DefaultAzureCredential()

    def _get_voicelive_endpoint(self) -> str:
        """Extract the base endpoint for Voice Live."""
        host = self.endpoint.replace("https://", "").replace("http://", "")
        host = host.split("/")[0]
        return f"https://{host}"

    async def _verify_agent_exists(self):
        """Verify the Foundry agent exists before connecting. Raises if not found."""
        # Use the new azure-ai-projects SDK (2.x) which matches how agents are created
        project_endpoint = f"{self.endpoint}/api/projects/{self.project_name}"
        try:
            client = AIProjectClient(
                endpoint=project_endpoint,
                credential=SyncDefaultAzureCredential(),
            )
            agent = client.agents.get(agent_name=self.agent_name)
            logger.info(f"Agent verified: {agent.name} (id={agent.id})")
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower() or "NotFound" in error_msg:
                raise ValueError(
                    f"Foundry Agent '{self.agent_name}' not found in project '{self.project_name}'. "
                    f"Please create the agent using: python scripts/create_agent.py"
                ) from e
            else:
                raise ValueError(
                    f"Failed to verify agent '{self.agent_name}': {error_msg}. "
                    f"Ensure FOUNDRY_AGENT_NAME and FOUNDRY_PROJECT_NAME are correct."
                ) from e

    async def connect(self, on_message: Callable):
        """Establish connection via Voice Live SDK in agent mode."""
        self._on_message = on_message

        # Verify agent exists before connecting
        await self._verify_agent_exists()

        credential = self._get_credential()
        voicelive_endpoint = self._get_voicelive_endpoint()

        agent_config: AgentSessionConfig = {
            "agent_name": self.agent_name,
            "project_name": self.project_name,
            "agent_version": self.agent_version,
            "conversation_id": self.conversation_id,
            "foundry_resource_override": self.foundry_resource_override,
        }

        logger.info(
            f"Connecting to Voice Live (Agent mode): endpoint={voicelive_endpoint}, "
            f"agent={self.agent_name}, project={self.project_name}"
        )

        self._connection_cm = connect(
            endpoint=voicelive_endpoint,
            credential=credential,
            agent_config=agent_config,
            api_version="2026-01-01-preview",
        )
        self._connection = await self._connection_cm.__aenter__()

        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("Connected to Voice Live (Agent mode)")

    async def _receive_loop(self):
        """Receive events from the Voice Live connection."""
        try:
            async for event in self._connection:
                logger.debug(f"Raw agent event: type={event.type}, attrs={[a for a in dir(event) if not a.startswith('_')]}")
                if self._on_message:
                    normalized = self._normalize_event(event)
                    if normalized:
                        await self._on_message(normalized)
                    else:
                        logger.info(f"Event not normalized (dropped): {event.type}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in Agent receive loop: {e}")

    def _normalize_event(self, event) -> Optional[dict]:
        """Convert Voice Live SDK events to normalized dict format for the frontend."""
        event_type = event.type

        if event_type == ServerEventType.SESSION_UPDATED:
            # Extract agent metadata if available
            session_info = {}
            if hasattr(event, "session") and event.session:
                session_info["id"] = event.session.id if event.session.id else ""
                if hasattr(event.session, "agent") and event.session.agent:
                    agent = event.session.agent
                    session_info["agent_name"] = getattr(agent, "name", "")
                    session_info["agent_description"] = getattr(agent, "description", "")
            return {"type": "session.updated", "session": session_info}

        elif event_type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            self._active_response = False
            return {"type": "input_audio_buffer.speech_started"}

        elif event_type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            return {"type": "input_audio_buffer.speech_stopped"}

        elif event_type == ServerEventType.RESPONSE_CREATED:
            self._active_response = True
            return {"type": "response.created"}

        elif event_type == ServerEventType.RESPONSE_AUDIO_DELTA:
            audio_b64 = base64.b64encode(event.delta).decode("utf-8") if event.delta else ""
            return {"type": "response.output_audio.delta", "delta": audio_b64}

        elif event_type == ServerEventType.RESPONSE_AUDIO_DONE:
            return {"type": "response.output_audio.done"}

        elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
            return {"type": "response.output_audio_transcript.delta", "delta": event.delta or ""}

        elif event_type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            return {"type": "response.output_audio_transcript.done", "transcript": event.transcript or ""}

        elif event_type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA:
            return {"type": "conversation.item.input_audio_transcription.delta", "delta": event.delta or ""}

        elif event_type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            return {"type": "conversation.item.input_audio_transcription.completed", "transcript": event.transcript or ""}

        elif event_type == ServerEventType.RESPONSE_DONE:
            self._active_response = False
            status_str = "unknown"
            if hasattr(event, 'response') and event.response:
                status_str = str(getattr(event.response, 'status', 'unknown'))
                logger.debug(f"Response done: status={status_str}")
            if "FAILED" in status_str.upper():
                return {"type": "error", "error": {"message": f"Response failed (status={status_str})"}}
            return {"type": "response.done"}

        elif event_type == ServerEventType.RESPONSE_TEXT_DONE:
            # Agent can respond with text (e.g., tool results displayed as text)
            text = getattr(event, "text", "") or ""
            return {"type": "response.text.done", "text": text}

        elif event_type == ServerEventType.ERROR:
            msg = event.error.message if event.error else "Unknown error"
            if "no active response" in msg.lower():
                logger.debug(f"Benign agent error: {msg}")
                return None
            return {"type": "error", "error": {"message": msg}}

        elif event_type == ServerEventType.CONVERSATION_ITEM_CREATED:
            # Agent handles tool calls internally; log for visibility
            if hasattr(event, "item") and event.item:
                item_type = getattr(event.item, "type", None)
                if item_type and "function" in str(item_type).lower():
                    name = getattr(event.item, "name", "unknown")
                    logger.info(f"Agent executing tool: {name}")
                    return {
                        "type": "tool.calling",
                        "name": name,
                        "arguments": "{}",  # Agent manages args internally
                    }
            return None

        else:
            logger.debug(f"Unhandled agent event: {event_type}")
            return None

    async def configure_session(self, tools: list[dict] = None, instructions: str = "", voice: str = "", **kwargs):
        """Configure the session. In agent mode, we send a minimal session.update
        to complete the handshake — the agent's metadata controls voice, turn detection, etc."""
        # Use the voice selected by the user, default to fr-CA-SylvieNeural
        voice_name = voice if voice else "fr-CA-SylvieNeural"
        # Detect language from voice name (e.g. "fr-CA-SylvieNeural" -> "fr-CA")
        lang_parts = voice_name.split("-")
        voice_lang = f"{lang_parts[0]}-{lang_parts[1]}" if len(lang_parts) >= 3 else "fr-CA"

        # Send a raw dict to avoid any SDK serialization issues with the type field.
        session_update_event = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "voice": {
                    "name": voice_name,
                    "type": "azure-standard",
                    "temperature": 0.8
                },
                "input_audio_transcription": {
                    "model": "azure-speech",
                    "language": voice_lang
                },
                "turn_detection": {
                    "type": "azure_semantic_vad",
                    "end_of_utterance_detection": {
                        "model": "semantic_detection_v1_multilingual"
                    }
                },
                "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
                "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
            }
        }

        await self._connection.send(session_update_event)
        logger.info(f"Agent session configured with voice={voice_name}, lang={voice_lang}")

    async def send_audio(self, audio_data: str):
        """Send audio data (base64 encoded PCM16) to Voice Live."""
        await self._connection.input_audio_buffer.append(audio=audio_data)

    async def commit_audio(self):
        """Commit audio buffer (no-op for agent mode, uses server VAD)."""
        pass

    async def send_tool_result(self, call_id: str, result: str):
        """No-op: Agent mode handles tool results internally."""
        logger.debug(f"Agent handles tool result internally (call_id={call_id})")

    async def cancel_response(self):
        """Cancel an in-progress response."""
        if self._active_response:
            try:
                await self._connection.response.cancel()
            except Exception as e:
                if "no active response" not in str(e).lower():
                    logger.debug(f"Cancel response: {e}")

    async def disconnect(self):
        """Close the Voice Live connection."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._connection_cm:
            try:
                await self._connection_cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._connection = None
        logger.info("Disconnected from Voice Live (Agent mode)")
