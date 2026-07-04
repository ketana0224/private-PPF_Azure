"""ローカル/リモート MCP サーバーの疎通スモークテスト。
list_tools と各ツールの呼び出しを検証する。
使い方: python smoke_test.py [BASE_URL]
  既定: http://localhost:8000/mcp
"""
import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])

            calls = [
                ("get_return_policy", {"category": "digital"}),
                ("get_return_policy", {"category": "general", "purchased_days_ago": 40}),
                ("get_shipping_policy", {"destination": "international"}),
                ("get_shipping_policy", {"destination": "domestic", "order_amount": 3000}),
                ("get_payment_policy", {"method": "クレジットカード"}),
                ("get_loyalty_points", {"customer_id": "C-1002"}),
            ]
            for name, args in calls:
                res = await session.call_tool(name, args)
                text = res.content[0].text if res.content else "(no content)"
                print(f"\n== {name}({args}) ==\n{text}")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"
    asyncio.run(main(base))
