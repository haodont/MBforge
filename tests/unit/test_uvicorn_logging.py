"""Uvicorn access-log noise filter contract.

Covers ``mbforge.foundation.logger.UvicornAccessLogFilter`` (successful
requests are dropped from the access log, errors and status-code-less records
survive) and ``configure_uvicorn_access_logging`` (the filter is installed on
the access logger and on its handlers).
"""

from __future__ import annotations

import logging

from mbforge.foundation.logger import (
    UvicornAccessLogFilter,
    configure_uvicorn_access_logging,
)

_SUCCESS_STATUS_CODES = (200, 201, 204, 299)
_NON_SUCCESS_STATUS_CODES = (100, 301, 400, 404, 500)


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


def test_filter_drops_successful_access_records_only() -> None:
    """2xx records are filtered; non-success and status-code-less records stay.

    Uvicorn sets ``status_code`` either as a record attribute or as the last
    positional log argument, so both shapes must be handled.
    """
    for as_uvicorn_args in (False, True):
        for status_code in _SUCCESS_STATUS_CODES:
            assert not UvicornAccessLogFilter().filter(
                _access_record(status_code, as_uvicorn_args=as_uvicorn_args)
            ), f"{status_code} (uvicorn_args={as_uvicorn_args}) must be filtered"
        for status_code in _NON_SUCCESS_STATUS_CODES:
            assert UvicornAccessLogFilter().filter(
                _access_record(status_code, as_uvicorn_args=as_uvicorn_args)
            ), f"{status_code} (uvicorn_args={as_uvicorn_args}) must be kept"

    assert UvicornAccessLogFilter().filter(_access_record(None)), (
        "record without status_code must be kept"
    )


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
