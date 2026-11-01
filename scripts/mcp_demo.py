"""Connect to the local ApplyWise MCP server and call its read-only tools."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.mcp_server import list_my_opportunities as list_opportunities_locally


async def main() -> None:
    print("Checking the ApplyWise opportunity function directly...")
    try:
        direct_result = list_opportunities_locally(status="all", limit=5)
    except Exception as exc:
        print(f"Direct function failed: {type(exc).__name__}: {exc}")
        return
    print("Direct function result:")
    print(json.dumps(direct_result, indent=2, default=str))

    server = StdioServerParameters(
        command=str(PROJECT_ROOT / ".venv314" / "Scripts" / "python.exe"),
        args=["-m", "app.mcp_server"],
        cwd=PROJECT_ROOT,
    )
    async with Client(server) as client:
        tools = await client.list_tools()
        print("ApplyWise MCP tools:")
        for tool in tools.tools:
            print(f"- {tool.name}: {tool.description}")
        result = await client.call_tool("list_my_opportunities", {"status": "all", "limit": 5})
        print("\nYour five most recent opportunities:")
        if result.is_error:
            print("MCP reported an error:")
            for item in result.content:
                if getattr(item, "text", None):
                    print(item.text)
        else:
            print(json.dumps(result.structured_content or result.content, indent=2, default=str))

        opportunities = direct_result if isinstance(direct_result, list) else []
        first_opportunity = next(
            (item for item in opportunities if isinstance(item, dict) and item.get("id")),
            None,
        )
        if first_opportunity:
            analysis = await client.call_tool(
                "get_my_latest_role_analysis",
                {"job_id": first_opportunity["id"]},
            )
            print("\nLatest saved role analysis for the first opportunity:")
            print(json.dumps(analysis.structured_content or analysis.content, indent=2, default=str))

        evidence = await client.call_tool(
            "search_my_profile_evidence",
            {"query": "AI machine learning Python project experience", "limit": 5},
        )
        print("\nLocal profile evidence search:")
        print(json.dumps(evidence.structured_content or evidence.content, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
