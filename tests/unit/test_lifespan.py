from __future__ import annotations

from contextlib import AsyncExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI


@pytest.mark.anyio
async def test_app_lifespan_does_not_load_models() -> None:
    from mbforge.app import lifespan

    app = FastAPI()
    with (
        patch("mbforge.adapters.inference.molparser.load") as mock_molparser_load,
        patch("mbforge.adapters.inference.moldet_v2_ft.get_moldet") as mock_moldet_ft,
        patch(
            "mbforge.adapters.runtime.process.shutdown._unload_backends"
        ) as mock_unload,
    ):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app))
            mock_unload.assert_not_called()
        mock_molparser_load.assert_not_called()
        mock_moldet_ft.assert_not_called()
        mock_unload.assert_called_once()


@pytest.mark.anyio
async def test_app_lifespan_prewarms_when_env_gate_is_on(monkeypatch) -> None:
    from mbforge.app import lifespan

    monkeypatch.setenv("MBFORGE_PREWARM_MODELS", "1")
    app = FastAPI()
    with (
        patch("mbforge.adapters.inference.molparser.load") as mock_molparser_load,
        patch("mbforge.adapters.inference.moldet_v2_ft.get_moldet") as mock_moldet_ft,
        patch(
            "mbforge.adapters.inference.prewarm.prewarm_models",
            return_value={"moldet": "ready", "molparser": "ready"},
        ) as mock_prewarm,
    ):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app))
            # Fire-and-forget prewarm runs in a thread; give it a beat to start.
            import asyncio

            await asyncio.sleep(0.05)
        mock_prewarm.assert_called_once()
        mock_molparser_load.assert_not_called()
        mock_moldet_ft.assert_not_called()
