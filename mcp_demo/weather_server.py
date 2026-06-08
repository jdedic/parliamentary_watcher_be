from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("weather")


@mcp.tool()
async def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://wttr.in/{city}?format=j1", timeout=10)
        r.raise_for_status()
        data = r.json()
        current = data["current_condition"][0]
        return {
            "city": city,
            "temp_c": current["temp_C"],
            "feels_like_c": current["FeelsLikeC"],
            "description": current["weatherDesc"][0]["value"],
            "humidity": current["humidity"],
        }


if __name__ == "__main__":
    mcp.run()
