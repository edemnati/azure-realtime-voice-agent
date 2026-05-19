"""Azure Voice Live client using the azure-ai-voicelive SDK."""

import asyncio
import base64
import json
import logging
from typing import Callable, Optional, Union

from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential

from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    AudioEchoCancellation,
    AudioInputTranscriptionOptions,
    AudioNoiseReduction,
    AzureSemanticVad,
    FunctionCallOutputItem,
    FunctionTool,
    InputAudioFormat,
    ItemType,
    Modality,
    OpenAIVoice,
    OutputAudioFormat,
    RequestSession,
    ServerEventType,
    ServerVad,
    ToolChoiceLiteral,
)

logger = logging.getLogger(__name__)


class FoundryRealtimeClient:
    """Client using the Azure Voice Live SDK for real-time voice conversation with function calling."""

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: Optional[str] = None,
        use_entra_id: bool = False,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.deployment = deployment
        self.api_key = api_key
        self.use_entra_id = use_entra_id
        self._connection = None
        self._connection_cm = None
        self._receive_task: Optional[asyncio.Task] = None
        self._on_message: Optional[Callable] = None
        self._pending_function_call: Optional[dict] = None

    def _get_credential(self) -> Union[AzureKeyCredential, AsyncTokenCredential]:
        """Get the appropriate credential."""
        if self.use_entra_id:
            return DefaultAzureCredential()
        else:
            return AzureKeyCredential(self.api_key or "")

    def _get_voicelive_endpoint(self) -> str:
        """Extract the base endpoint for Voice Live (services.ai.azure.com format)."""
        host = self.endpoint.replace("https://", "").replace("http://", "")
        host = host.split("/")[0]
        return f"https://{host}"

    async def connect(self, on_message: Callable):
        """Establish connection via the Voice Live SDK."""
        self._on_message = on_message
        credential = self._get_credential()
        voicelive_endpoint = self._get_voicelive_endpoint()

        logger.info(f"Connecting to Voice Live API (endpoint={voicelive_endpoint}, model={self.deployment})...")

        self._connection_cm = connect(
            endpoint=voicelive_endpoint,
            credential=credential,
            model=self.deployment,
        )
        self._connection = await self._connection_cm.__aenter__()

        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("Connected to Voice Live API")

    async def _receive_loop(self):
        """Receive events from the Voice Live connection and forward as normalized dicts."""
        try:
            async for event in self._connection:
                if self._on_message:
                    normalized = self._normalize_event(event)
                    if normalized:
                        await self._on_message(normalized)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in Voice Live receive loop: {e}")

    def _normalize_event(self, event) -> Optional[dict]:
        """Convert Voice Live SDK events to the same dict format used by the raw WS client."""
        event_type = event.type

        if event_type == ServerEventType.SESSION_UPDATED:
            return {"type": "session.updated", "session": {"id": event.session.id if event.session else ""}}

        elif event_type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            return {"type": "input_audio_buffer.speech_started"}

        elif event_type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            return {"type": "input_audio_buffer.speech_stopped"}

        elif event_type == ServerEventType.RESPONSE_CREATED:
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
            # Execute pending function call after response completes
            if self._pending_function_call and "arguments" in self._pending_function_call:
                # Emit the function call event for main.py to handle via LangGraph
                call_info = self._pending_function_call
                self._pending_function_call = None
                return {
                    "type": "response.function_call_arguments.done",
                    "name": call_info["name"],
                    "arguments": call_info["arguments"],
                    "call_id": call_info["call_id"],
                }
            return {"type": "response.done"}

        elif event_type == ServerEventType.ERROR:
            msg = event.error.message if event.error else "Unknown error"
            return {"type": "error", "error": {"message": msg}}

        elif event_type == ServerEventType.CONVERSATION_ITEM_CREATED:
            if hasattr(event, "item") and event.item and event.item.type == ItemType.FUNCTION_CALL:
                # Track the pending function call
                self._pending_function_call = {
                    "name": event.item.name,
                    "call_id": event.item.call_id,
                    "previous_item_id": event.item.id,
                }
                logger.info(f"Function call detected: {event.item.name} (call_id={event.item.call_id})")
            return None

        elif event_type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            # Store arguments on the pending call; will be emitted on RESPONSE_DONE
            if self._pending_function_call and event.call_id == self._pending_function_call["call_id"]:
                self._pending_function_call["arguments"] = event.arguments
                logger.info(f"Function arguments received: {event.arguments}")
            return None

        else:
            logger.debug(f"Unhandled Voice Live event: {event_type}")
            return None

    def _convert_tools(self, tools: list[dict]) -> list[FunctionTool]:
        """Convert raw tool definition dicts to FunctionTool objects for the SDK."""
        function_tools = []
        for tool in tools:
            function_tools.append(FunctionTool(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=tool.get("parameters", {}),
            ))
        return function_tools

    async def configure_session(self, tools: list[dict], instructions: str = "", voice: str = "alloy", **kwargs):
        """Configure the Voice Live session with function tools."""
        default_instructions = (
            "You are a helpful, friendly voice assistant. "
            "You speak clearly and concisely. "
            "You can help with getting the current time, weather information, "
            "and searching the company knowledge base. "
            "Always be polite and professional."
        )

        # Build turn detection based on options
        turn_detection_type = kwargs.get("turn_detection", "server_vad")
        vad_threshold = kwargs.get("vad_threshold", 0.5)
        silence_duration = kwargs.get("silence_duration", 500)

        if turn_detection_type == "semantic_vad":
            turn_detection = AzureSemanticVad(
                threshold=vad_threshold,
                prefix_padding_ms=300,
                silence_duration_ms=silence_duration,
            )
        else:
            turn_detection = ServerVad(
                threshold=vad_threshold,
                prefix_padding_ms=300,
                silence_duration_ms=silence_duration,
            )

        function_tools = self._convert_tools(tools)

        session_config = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=instructions or default_instructions,
            voice=OpenAIVoice(name=voice),
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            turn_detection=turn_detection,
            tools=function_tools,
            tool_choice=ToolChoiceLiteral.AUTO,
            input_audio_transcription=AudioInputTranscriptionOptions(model="whisper-1"),
        )

        # Apply optional session parameters
        temperature = kwargs.get("temperature")
        if temperature is not None:
            session_config.temperature = temperature

        max_tokens = kwargs.get("max_tokens")
        if max_tokens is not None:
            session_config.max_response_output_tokens = max_tokens

        if kwargs.get("noise_reduction"):
            session_config.input_audio_noise_reduction = AudioNoiseReduction(type="azure_deep_noise_suppression")

        if kwargs.get("echo_cancellation"):
            session_config.input_audio_echo_cancellation = AudioEchoCancellation()

        await self._connection.session.update(session=session_config)
        logger.info("Voice Live session configured (with function tools)")

    async def send_audio(self, audio_data: str):
        """Send audio data (base64 encoded PCM16) to Voice Live."""
        await self._connection.input_audio_buffer.append(audio=audio_data)

    async def commit_audio(self):
        """Commit the audio buffer (Voice Live uses server VAD, this is a no-op)."""
        pass

    async def send_tool_result(self, call_id: str, result: str):
        """Send a tool call result back to the Voice Live session."""
        function_output = FunctionCallOutputItem(
            call_id=call_id,
            output=result,
        )
        await self._connection.conversation.item.create(item=function_output)
        # Request a new response so the model incorporates the tool result
        await self._connection.response.create()
        logger.info(f"Tool result sent for call_id={call_id}")

    async def cancel_response(self):
        """Cancel an in-progress response."""
        try:
            await self._connection.response.cancel()
        except Exception as e:
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
        logger.info("Disconnected from Voice Live API")
