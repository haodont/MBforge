from __future__ import annotations

import logging

import pytest

from mbforge.foundation.logger import (
    UvicornAccessLogFilter,
    configure_uvicorn_access_logging,
)


def _access_record(
    status_code: int | None, *, as_uvicorn_args: bool = False
) -> logging.LogRecord:
    args: tuple[object, ...] = ()
    if as_uvicorn_args:
        args = ("127.0.0.1:1234", "GET", "/health", "1.1", status_code)
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=args,
        exc_info=None,
    )
    if status_code is not None:
        record.status_code = status_code
    return record


@pytest.mark.parametrize("as_uvicorn_args", [False, True])
@pytest.mark.parametrize("status_code", [200, 201, 204, 299])
def test_successful_access_records_are_filtered(
    status_code: int, as_uvicorn_args: bool
) -> None:
    assert not UvicornAccessLogFilter().filter(
        _access_record(status_code, as_uvicorn_args=as_uvicorn_args)
    )


@pytest.mark.parametrize("as_uvicorn_args", [False, True])
@pytest.mark.parametrize("status_code", [100, 301, 400, 404, 500])
def test_non_success_access_records_are_kept(
    status_code: int, as_uvicorn_args: bool
) -> None:
    assert UvicornAccessLogFilter().filter(
        _access_record(status_code, as_uvicorn_args=as_uvicorn_args)
    )


def test_access_record_without_status_code_is_kept() -> None:
    assert UvicornAccessLogFilter().filter(_access_record(None))


def test_configure_installs_filter_on_access_handlers() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    handler = logging.NullHandler()
    original_filters = list(access_logger.filters)
    access_logger.addHandler(handler)
    try:
        configure_uvicorn_access_logging()
        assert any(
            isinstance(item, UvicornAccessLogFilter) for item in access_logger.filters
        )
        assert any(isinstance(item, UvicornAccessLogFilter) for item in handler.filters)
    finally:
        access_logger.removeHandler(handler)
        access_logger.filters[:] = original_filters
