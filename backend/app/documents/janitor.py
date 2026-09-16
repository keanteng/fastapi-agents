from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.documents.storage import purge_expired_uploads

logger = logging.getLogger(__name__)

MAX_INTERVAL_SECONDS = 3600.0
MIN_INTERVAL_SECONDS = 60.0


async def upload_janitor_loop() -> None:
    """Periodically delete uploads older than ``UPLOAD_TTL_SECONDS``."""
    ttl = settings.upload_ttl_seconds
    if ttl <= 0:
        return
    interval = min(max(MIN_INTERVAL_SECONDS, ttl / 4), MAX_INTERVAL_SECONDS)
    while True:
        try:
            removed = await asyncio.to_thread(purge_expired_uploads, ttl)
            if removed:
                logger.info("upload janitor removed %d expired upload(s)", removed)
        except Exception:  # noqa: BLE001 - janitor must never crash the app
            logger.exception("upload janitor sweep failed")
        await asyncio.sleep(interval)
