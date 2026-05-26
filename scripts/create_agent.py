"""Create a Foundry Agent with Voice Live enabled.

This script creates (or updates) an Azure AI Foundry Agent configured for
real-time voice interaction via the Voice Live SDK.

Prerequisites:
    1. A Microsoft Foundry project with a model deployed.
    2. You must be logged in via `az login --tenant <tenant-id>`.

Usage:
    python scripts/create_agent.py

Environment variables (from .env):
    PROJECT_ENDPOINT    - Foundry project endpoint (https://resource.ai.azure.com/api/projects/project)
    FOUNDRY_AGENT_NAME  - Name for the agent
    FOUNDRY_AGENT_MODEL - Model deployment (e.g. gpt-5-mini)
"""

import json
import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Format: "https://resource_name.ai.azure.com/api/projects/project_name"
PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT", "").strip()
AGENT_NAME = os.getenv("FOUNDRY_AGENT_NAME", "MyVoiceAgent").strip()
MODEL = os.getenv("FOUNDRY_AGENT_MODEL", "gpt-5-mini")

# Agent instructions - customize as needed
AGENT_INSTRUCTIONS = """You are a helpful voice assistant powered by Azure AI Foundry.
You respond in a natural conversational tone. Keep answers concise and clear.
When the user asks a question, provide a direct answer.
If you don't know something, say so honestly.
You have access to a file search tool that contains reference documents. Use it when the user asks questions about plans, policies, or actions."""

# Path to documents folder for file_search tool
DOC_FOLDER = os.path.join(os.path.dirname(__file__), "..", "doc")

# Voice Live session configuration (stored in agent metadata)
VOICE_LIVE_CONFIG = {
    "session": {
        "voice": {
            "name": "fr-CA-SylvieNeural",
            "type": "azure-standard",
            "temperature": 0.8
        },
        "input_audio_transcription": {
            "model": "azure-speech",
            "language": "fr-CA"
        },
        "turn_detection": {
            "type": "azure_semantic_vad",
            "end_of_utterance_detection": {
                "model": "semantic_detection_v1_multilingual"
            }
        },
        "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
        "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
        "interim_response": {
            "type": "llm",
            "triggers": ["tool", "latency"],
            "latency_threshold_ms": 100,
            "instructions": "Create friendly interim responses indicating wait time due to ongoing processing. Do not say you don't have real-time access to information when calling tools."
        }
    }
}


def chunk_config(config_json: str, limit: int = 512) -> dict:
    """Split config into chunked metadata entries using the microsoft.voice-live key."""
    metadata = {"microsoft.voice-live.configuration": config_json[:limit]}
    remaining = config_json[limit:]
    chunk_num = 1
    while remaining:
        metadata[f"microsoft.voice-live.configuration.{chunk_num}"] = remaining[:limit]
        remaining = remaining[limit:]
        chunk_num += 1
    return metadata


def reassemble_config(metadata: dict) -> str:
    """Reassemble chunked Voice Live configuration."""
    config = metadata.get("microsoft.voice-live.configuration", "")
    chunk_num = 1
    while f"microsoft.voice-live.configuration.{chunk_num}" in metadata:
        config += metadata[f"microsoft.voice-live.configuration.{chunk_num}"]
        chunk_num += 1
    return config


def upload_documents(project):
    """Upload documents from doc/ folder and create a vector store for file_search."""
    if not os.path.isdir(DOC_FOLDER):
        print(f"  No doc/ folder found at {DOC_FOLDER}, skipping file_search setup.")
        return None

    files = [f for f in os.listdir(DOC_FOLDER) if os.path.isfile(os.path.join(DOC_FOLDER, f))]
    if not files:
        print("  No files found in doc/ folder, skipping file_search setup.")
        return None

    oai = project.get_openai_client()
    uploaded_file_ids = []

    for filename in files:
        filepath = os.path.join(DOC_FOLDER, filename)
        print(f"  Uploading: {filename}")
        with open(filepath, "rb") as f:
            uploaded = oai.files.create(file=f, purpose="assistants")
        uploaded_file_ids.append(uploaded.id)
        print(f"    -> file_id: {uploaded.id}")

    print(f"  Creating vector store with {len(uploaded_file_ids)} file(s)...")
    vector_store = oai.vector_stores.create(
        file_ids=uploaded_file_ids,
        name=f"{AGENT_NAME}-documents",
    )
    print(f"    -> vector_store_id: {vector_store.id}")
    return vector_store.id


def create_agent():
    """Create or update the Foundry agent with Voice Live configuration."""
    if not PROJECT_ENDPOINT:
        print("ERROR: PROJECT_ENDPOINT is not set in .env")
        print("  Format: https://resource_name.ai.azure.com/api/projects/project_name")
        sys.exit(1)
    if not AGENT_NAME:
        print("ERROR: FOUNDRY_AGENT_NAME is not set in .env")
        sys.exit(1)

    print(f"Endpoint:   {PROJECT_ENDPOINT}")
    print(f"Agent Name: {AGENT_NAME}")
    print(f"Model:      {MODEL}")
    print()

    # Create project client (new Foundry SDK 2.x)
    project = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )

    # Build metadata with Voice Live config using the official key format
    metadata = chunk_config(json.dumps(VOICE_LIVE_CONFIG))

    # Upload documents and create vector store for file_search
    print("Setting up file_search tool...")
    vector_store_id = upload_documents(project)

    tools = []
    if vector_store_id:
        tools.append(FileSearchTool(vector_store_ids=[vector_store_id]))
        print(f"  file_search tool configured with vector_store: {vector_store_id}")

    try:
        # Create agent version using the new Foundry API
        print("Creating agent version...")
        agent = project.agents.create_version(
            agent_name=AGENT_NAME,
            definition=PromptAgentDefinition(
                model=MODEL,
                instructions=AGENT_INSTRUCTIONS,
                tools=tools if tools else None,
            ),
            metadata=metadata,
        )
        print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")
    except HttpResponseError as e:
        print(f"\nERROR: Failed to create agent: {e}")
        sys.exit(1)

    # Verify Voice Live configuration was stored correctly
    print("\nVerifying Voice Live configuration...")
    retrieved_agent = project.agents.get(agent_name=AGENT_NAME)
    stored_metadata = (retrieved_agent.versions or {}).get("latest", {}).get("metadata", {})
    stored_config = reassemble_config(stored_metadata)

    if stored_config:
        config = json.loads(stored_config)
        voice = config.get("session", {}).get("voice", {})
        turn = config.get("session", {}).get("turn_detection", {})
        print(f"  Voice:            {voice.get('name', 'N/A')}")
        print(f"  Voice Type:       {voice.get('type', 'N/A')}")
        print(f"  Turn Detection:   {turn.get('type', 'N/A')}")
        print(f"  Noise Reduction:  {config.get('session', {}).get('input_audio_noise_reduction', {}).get('type', 'N/A')}")
        print(f"  Echo Cancellation: {config.get('session', {}).get('input_audio_echo_cancellation', {}).get('type', 'N/A')}")
    else:
        print("  WARNING: Voice Live configuration not found in agent metadata.")

    print()
    print("Done! You can now use the agent in the app with client mode = 'agent'.")
    print(f"  FOUNDRY_AGENT_NAME={AGENT_NAME}")


if __name__ == "__main__":
    create_agent()
