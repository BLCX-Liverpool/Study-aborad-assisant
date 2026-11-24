"""Backward-compatible imports for Google Maps tools moved out of the MCP layer."""

from app.tools.google_maps import GoogleMapsDirectionsTool, GoogleMapsPlacesTool
from app.tools.mcp import build_tavily_mcp_tools


def BrowserMcpSearchExtractTool():
    """Return the deprecated explicit-call compatibility wrapper."""
    return build_tavily_mcp_tools()[-1]


__all__ = ["BrowserMcpSearchExtractTool", "GoogleMapsDirectionsTool", "GoogleMapsPlacesTool"]
