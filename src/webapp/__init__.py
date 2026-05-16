"""Zero-dependency web UI for the Python porting workspace.

Exposes every ``src.main`` CLI capability through a browser interface backed
by a standard-library HTTP server.
"""

from __future__ import annotations

from .server import create_server, serve

__all__ = ['create_server', 'serve']
