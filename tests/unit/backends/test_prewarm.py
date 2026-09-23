from unittest.mock import Mock, patch

from mbforge.adapters.inference.prewarm import prewarm_models


def _ready_detector() -> Mock:
    detector = Mock()
    detector.is_available.return_value = True
    return detector


def test_prewarm_reports_each_model_status() -> None:
    with (
        patch(
            "mbforge.adapters.inference.moldet_v2_ft.get_moldet",
            return_value=_ready_detector(),
        ),
        patch("mbforge.adapters.inference.molparser.load"),
        patch(
            "mbforge.adapters.inference.molparser.health",
            return_value={"status": "ready"},
        ),
    ):
        assert prewarm_models() == {"moldet": "ready", "molparser": "ready"}


def test_prewarm_backend_exception_reported_as_error() -> None:
    with (
        patch(
            "mbforge.adapters.inference.moldet_v2_ft.get_moldet",
            side_effect=RuntimeError("missing"),
        ),
        patch("mbforge.adapters.inference.molparser.load"),
        patch(
            "mbforge.adapters.inference.molparser.health",
            return_value={"status": "ready"},
        ),
    ):
        assert prewarm_models() == {"moldet": "error", "molparser": "ready"}


def test_prewarm_marks_unusable_models_unavailable() -> None:
    detector = Mock()
    detector.is_available.return_value = False
    with (
        patch(
            "mbforge.adapters.inference.moldet_v2_ft.get_moldet", return_value=detector
        ),
        patch("mbforge.adapters.inference.molparser.load"),
        patch(
            "mbforge.adapters.inference.molparser.health",
            return_value={"status": "error"},
        ),
    ):
        assert prewarm_models() == {"moldet": "unavailable", "molparser": "error"}
