from __future__ import annotations

import logging

from src.server.book_manager import BookManager

logger = logging.getLogger("polymarket")
registry = BookManager()
