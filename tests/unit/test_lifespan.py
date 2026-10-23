from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI


@pytest.mark.anyio
async def test_app_lifespan_never_eagerly_loads_models_and_prewarms_only_when_gated(
    monkeypatch,
) -> None:
    """Startup must not import model backends; the opt-in prewarm gate runs
    ``prewarm_models`` fire-and-forget, and shutdown always runs the ordered
    backend unload exactly once."""
    from mbforge.server.app import lifespan

    app = FastAPI()
    monkeypatch.delenv("MBFORGE_PREWARM_MODELS", raising=False)
    with (
        patch("mbforge.foundation.inference.molparser.load") as mock_molparser_load,
        patch("mbforge.foundation.inference.moldet_v2_ft.get_moldet") as mock_moldet_ft,
        patch(
            "mbforge.foundation.inference.prewarm.prewarm_models",
            return_value={"moldet": "ready", "molparser": "ready"},
        ) as mock_prewarm,
        patch("mbforge.server.process.shutdown._unload_backends") as mock_unload,
    ):
        # Gate off: nothing prewarms, models stay unloaded, shutdown unloads once.
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app))
            mock_unload.assert_not_called()
        mock_prewarm.assert_not_called()
        mock_molparser_load.assert_not_called()
        mock_moldet_ft.assert_not_called()
        mock_unload.assert_called_once()

        # Gate on: prewarm runs in the background, still no eager backend load.
        mock_unload.reset_mock()
        monkeypatch.setenv("MBFORGE_PREWARM_MODELS", "1")
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app))
            # Fire-and-forget prewarm runs in a thread; give it a beat to start.
            await asyncio.sleep(0.05)
        mock_prewarm.assert_called_once()
        mock_molparser_load.assert_not_called()
        mock_moldet_ft.assert_not_called()
