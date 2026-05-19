"""Azure OpenAI Realtime API WebSocket client."""

import json
import asyncio
import logging
from typing import Callable, Optional

import websockets
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# API mode constants
MODE_GA = "ga"          # GA format for gpt-realtime-mini, gpt-realtime, gpt-realtime-1.5


class RealtimeClient:
    """Client for managing WebSocket connections to Azure OpenAI Realtime API."""

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: Optional[str] = None,
        use_entra_id: bool = False,
        api_mode: str = MODE_GA,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.deployment = deployment
        self.api_key = api_key
        self.use_entra_id = use_entra_id
        self.api_mode = api_mode
        self.ws = None
        self._receive_task: Optional[asyncio.Task] = None
        self._on_message: Optional[Callable] = None

    def _build_url(self) -> str:
        """Build the WebSocket URL for the Realtime API."""
        # Extract just the hostname from the endpoint URL
        host = self.endpoint.replace("https://", "").replace("http://", "")
        # Strip any path components (e.g., /openai/v1) to get just the hostname
        host = host.split("/")[0]
        # Use the GA endpoint format: /openai/v1/realtime?model=<deployment>
        url = f"wss://{host}/openai/v1/realtime?model={self.deployment}"
        if self.api_key and not self.use_entra_id:
            url += f"&api-key={self.api_key}"
        return url

    def _get_headers(self) -> dict:
        """Get authentication headers."""
        headers = {}
        if self.use_entra_id:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            headers["Authorization"] = f"Bearer {token.token}"
        elif self.api_key:
            headers["api-key"] = self.api_key
        return headers

    async def connect(self, on_message: Callable):
        """Establish WebSocket connection to the Realtime API."""
        self._on_message = on_message
        url = self._build_url()
        headers = self._get_headers()

        logger.info(f"Connecting to Realtime API: {url.split('?')[0]}...")

        self.ws = await websockets.connect(
            url,
            additional_headers=headers,
            max_size=None,
        )

        # Start receiving messages
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("Connected to Realtime API")

    async def _receive_loop(self):
        """Continuously receive messages from the Realtime API."""
        try:
            async for message in self.ws:
                if self._on_message:
                    data = json.loads(message)
                    await self._on_message(data)
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Realtime API connection closed: {e}")
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")

    async def send(self, event: dict):
        """Send an event to the Realtime API."""
        if self.ws:
            try:
                await self.ws.send(json.dumps(event))
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Cannot send: WebSocket connection is closed")
        else:
            logger.warning("Cannot send: WebSocket is not connected")

    async def configure_session(self, tools: list[dict], instructions: str = "", voice: str = "alloy", **kwargs):
        """Send session configuration to the Realtime API."""
        default_instructions = (
            "You are a helpful, friendly voice assistant. "
            "You speak clearly and concisely. "
            "You can help with getting the current time, weather information, "
            "and searching the company knowledge base. "
            "Always be polite and professional."
        )

        session_config = self._build_ga_session_config(
            tools, instructions or default_instructions, voice, **kwargs
        )

        await self.send(session_config)
        logger.info("Session configured")

    def _build_ga_session_config(self, tools: list[dict], instructions: str, voice: str, **kwargs) -> dict:
        """Build session config for GA models (gpt-realtime-mini, gpt-realtime, gpt-realtime-1.5)."""
        vad_threshold = kwargs.get("vad_threshold", 0.5)
        silence_duration = kwargs.get("silence_duration", 500)
        max_tokens = kwargs.get("max_tokens")
        noise_reduction = kwargs.get("noise_reduction", False)

        input_audio_config = {
            "format": {"type": "audio/pcm", "rate": 24000},
            "transcription": {
                "model": "whisper-1"
            },
            "turn_detection": {
                "type": "server_vad",
                "threshold": vad_threshold,
                "prefix_padding_ms": 300,
                "silence_duration_ms": silence_duration,
                "create_response": True,
            },
        }

        if noise_reduction:
            input_audio_config["noise_reduction"] = {"type": "near_field"}

        config = {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": instructions,
                "audio": {
                    "input": input_audio_config,
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": voice,
                    },
                },
                "tools": tools,
                "tool_choice": "auto",
            },
        }

        if max_tokens is not None:
            config["session"]["max_response_output_tokens"] = max_tokens

        return config

    async def send_audio(self, audio_data: str):
        """Send audio data (base64 encoded PCM16) to the Realtime API."""
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_data,
        }
        await self.send(event)

    async def commit_audio(self):
        """Commit the audio buffer (for manual turn handling)."""
        await self.send({"type": "input_audio_buffer.commit"})

    async def send_tool_result(self, call_id: str, result: str):
        """Send a tool call result back to the Realtime API."""
        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            },
        }
        await self.send(event)
        # Trigger response generation after providing tool output
        await self.send({"type": "response.create"})

    async def cancel_response(self):
        """Cancel an in-progress response."""
        await self.send({"type": "response.cancel"})

    async def disconnect(self):
        """Close the WebSocket connection."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
            logger.info("Disconnected from Realtime API")
