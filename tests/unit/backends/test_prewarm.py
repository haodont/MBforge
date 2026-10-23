"""Prewarm status-report contract for the optional local models.

Covers ``mbforge.foundation.inference.prewarm.prewarm_models``: each backend
contributes its own status (``ready`` / ``error`` / ``unavailable``) so the
opt-in startup prewarm surfaces which features are usable.
"""

from unittest.mock import Mock, patch

from mbforge.foundation.inference.prewarm import prewarm_models


def _ready_detector() -> Mock:
    detector = Mock()
    detector.is_available.return_value = True
    return detector


def test_prewarm_reports_each_model_status() -> None:
    """A ready detector reports ``ready``; a raised backend error reports
    ``error``; a detector that is present but unusable reports ``unavailable``;
    the molparser health status is passed through unchanged."""
    with (
        patch(
            "mbforge.foundation.inference.moldet_v2_ft.get_moldet",
            return_value=_ready_detector(),
        ),
        patch("mbforge.foundation.inference.molparser.load"),
        patch(
            "mbforge.foundation.inference.molparser.health",
            return_value={"status": "ready"},
        ),
    ):
        assert prewarm_models() == {"moldet": "ready", "molparser": "ready"}

    with (
        patch(
            "mbforge.foundation.inference.moldet_v2_ft.get_moldet",
            side_effect=RuntimeError("missing"),
        ),
        patch("mbforge.foundation.inference.molparser.load"),
        patch(
            "mbforge.foundation.inference.molparser.health",
            return_value={"status": "ready"},
        ),
    ):
        assert prewarm_models() == {"moldet": "error", "molparser": "ready"}

    detector = Mock()
    detector.is_available.return_value = False
    with (
        patch(
            "mbforge.foundation.inference.moldet_v2_ft.get_moldet",
            return_value=detector,
        ),
        patch("mbforge.foundation.inference.molparser.load"),
        patch(
            "mbforge.foundation.inference.molparser.health",
            return_value={"status": "error"},
        ),
    ):
        assert prewarm_models() == {"moldet": "unavailable", "molparser": "error"}
