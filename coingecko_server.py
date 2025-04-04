import asyncio
import logging
import os
from typing import Any, Dict, List

import aiohttp
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# Configuration
class Config:
    PORT = int(os.environ.get("PORT", 8001))  # Changed default port
    COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
    LOG_LEVEL = logging.INFO
    LOGGER_NAME = "coingecko-mcp-server"

logger = logging.getLogger(Config.LOGGER_NAME)
logger.setLevel(Config.LOG_LEVEL)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# MCP Server Implementation
class CoinGeckoServer:
    def __init__(self):
        self.server = None

    async def get_coin_price(self, coin_id: str) -> Dict[str, Any]:
        """Fetches the current price of a coin from CoinGecko."""
        url = f"{Config.COINGECKO_API_URL}/simple/price?ids={coin_id}&vs_currencies=usd"
        logger.info(f"Fetching price for {coin_id} from {url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if coin_id in data and "usd" in data[coin_id]:
                            return {"price": data[coin_id]["usd"]}
                        else:
                            logger.warning(f"Could not retrieve USD price for {coin_id}")
                            return {"price": None}
                    else:
                        logger.error(f"Error fetching price for {coin_id}: {response.status}")
                        return {"price": None}
        except Exception as e:
            logger.exception(f"Error fetching price for {coin_id}: {e}")
            return {"price": None}

    async def initialize(self) -> Server:
        self.server = self._create_server()
        return self.server

    def _create_server(self) -> Server:
        app = Server("coingecko-mcp-server")

        @app.list_tools()
        async def list_tools() -> List[Dict[str, Any]]:
            return [
                {
                    "name": "get_coin_price",
                    "description": "Gets the current price of a coin from CoinGecko.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "coin_id": {
                                "type": "string",
                                "description": "The CoinGecko ID of the coin (e.g., bitcoin, ethereum)."
                            }
                        },
                        "required": ["coin_id"]
                    }
                }
            ]

        @app.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
            if name == "get_coin_price":
                coin_id = arguments.get("coin_id")
                if not coin_id:
                    raise ValueError("coin_id is required")
                price_data = await self.get_coin_price(coin_id)
                return [{"type": "text", "text": str(price_data)}]
            else:
                raise ValueError(f"Unknown tool: {name}")

        return app

    async def run_sse(self, port: int):
        if not self.server:
            await self.initialize()

        messages_path = "/messages/"
        sse = SseServerTransport(messages_path)

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await self.server.run(streams[0], streams[1], self.server.create_initialization_options())

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )

        logger.info(f"Starting SSE server on port {port}")
        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port)
        server = uvicorn.Server(config)
        await server.serve()

async def main():
    server = CoinGeckoServer()
    await server.run_sse(Config.PORT)

if __name__ == "__main__":
    asyncio.run(main())
