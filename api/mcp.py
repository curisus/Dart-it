"""Vercel entry point: the file path fixes the served URL at /api/mcp."""

from dart_crawler.remote_server import build_app

app = build_app()
