"""Tool definitions for the LangGraph agent used with the Realtime API."""

import json
from datetime import datetime


def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_weather(location: str) -> str:
    """Get weather information for a given location (simulated)."""
    # Simulated weather data for demo purposes
    weather_data = {
        "New York": {"temp": "72°F", "condition": "Partly Cloudy"},
        "London": {"temp": "15°C", "condition": "Rainy"},
        "Tokyo": {"temp": "28°C", "condition": "Sunny"},
        "Paris": {"temp": "20°C", "condition": "Overcast"},
    }
    data = weather_data.get(location, {"temp": "N/A", "condition": "Unknown location"})
    return f"Weather in {location}: {data['temp']}, {data['condition']}"


def search_knowledge_base(query: str) -> str:
    """Search a knowledge base for information (simulated)."""
    # Simulated knowledge base responses
    responses = {
        "company": "Contoso Ltd is a global technology company founded in 2010.",
        "product": "Our flagship product is the Contoso AI Assistant, launched in 2024.",
        "support": "For support, contact support@contoso.com or call 1-800-CONTOSO.",
    }
    for key, value in responses.items():
        if key in query.lower():
            return value
    return f"No specific information found for: {query}"


# Tool definitions in the format expected by the Realtime API
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "get_current_time",
        "description": "Get the current date and time. Use this when the user asks what time or date it is.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get current weather information for a specified location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city name to get weather for (e.g., 'New York', 'London', 'Tokyo')",
                }
            },
            "required": ["location"],
        },
    },
    {
        "type": "function",
        "name": "search_knowledge_base",
        "description": "Search the company knowledge base for information about products, company details, or support.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up in the knowledge base",
                }
            },
            "required": ["query"],
        },
    },
]

# Map of tool names to their implementations
TOOL_IMPLEMENTATIONS = {
    "get_current_time": get_current_time,
    "get_weather": get_weather,
    "search_knowledge_base": search_knowledge_base,
}


def execute_tool(name: str, arguments: str) -> str:
    """Execute a tool by name with the given JSON arguments string."""
    func = TOOL_IMPLEMENTATIONS.get(name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        args = json.loads(arguments) if arguments else {}
        result = func(**args)
        return result
    except Exception as e:
        return json.dumps({"error": str(e)})
