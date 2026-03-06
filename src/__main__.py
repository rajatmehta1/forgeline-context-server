"""
ForgeLine Context Server — Entry Point

Usage:
    python -m src.server                                    # stdio (IDE integration)
    python -m src.server --transport streamable-http        # HTTP mode
    python -m src.server --transport sse --port 8080        # SSE mode
"""

from __future__ import annotations

import argparse
import sys

from src.server import mcp
from src.config.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="ForgeLine Pre-Generation Context Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=settings.transport,
        help="MCP transport mode (default: stdio for IDE, streamable-http for remote)",
    )
    parser.add_argument("--host", default=settings.server_host, help="Server host")
    parser.add_argument("--port", type=int, default=settings.server_port, help="Server port")

    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        print(f"Unknown transport: {args.transport}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
