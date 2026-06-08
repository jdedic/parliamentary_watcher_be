import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(
    command="python",
    args=["mcp_demo/weather_server.py"],
)


async def main():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. discover what tools the server exposes
            tools = await session.list_tools()
            print("Available tools:", [t.name for t in tools.tools])

            # 2. call a tool directly
            result = await session.call_tool("get_weather", {"city": "Amsterdam"})
            print("Weather result:", result.content[0].text)

            # 3. show OpenAI-compatible schema — ready to pass to chat.completions(tools=...)
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema,
                    },
                }
                for t in tools.tools
            ]
            print("\nOpenAI tool schema:")
            print(json.dumps(openai_tools, indent=2))


asyncio.run(main())
