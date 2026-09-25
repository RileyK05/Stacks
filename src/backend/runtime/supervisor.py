"""App-lifetime care of the local model server: clean up a server left by
a crashed launch, bring back the model that was running last time, restart
it if it crashes, and stop it when the app exits."""

from __future__ import annotations

import asyncio
import logging

from src.backend.common import settings_repo
from src.backend.runtime.server import (
    ACTIVE_MODEL_SETTING,
    RuntimeUnavailableError,
    cleanup_stale_server,
    get_server,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 10.0


def _resume_last_model() -> None:
    model_id = settings_repo.get_setting(ACTIVE_MODEL_SETTING)
    if not model_id:
        return
    try:
        get_server().start(str(model_id))
    except RuntimeUnavailableError:
        logger.exception("could not resume local model %s", model_id)


async def run_forever(stop: asyncio.Event) -> None:
    await asyncio.to_thread(cleanup_stale_server)
    # Resume in the background: the UI is usable while the model loads.
    resume = asyncio.create_task(asyncio.to_thread(_resume_last_model))
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except TimeoutError:
                await asyncio.to_thread(get_server().check_and_restart)
    finally:
        if not resume.done():
            await resume
        await asyncio.to_thread(_stop_without_forgetting)


def _stop_without_forgetting() -> None:
    """Stop the process on shutdown but keep the active-model setting, so
    the next launch resumes it (unlike an explicit Stop from the UI)."""
    server = get_server()
    remembered = settings_repo.get_setting(ACTIVE_MODEL_SETTING)
    server.stop()
    if remembered:
        settings_repo.put_setting(ACTIVE_MODEL_SETTING, remembered)
