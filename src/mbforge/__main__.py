"""python -m mbforge — start the MBForge web application.

The React frontend at http://<host>:<port>/ is the only official UI.
In dev mode (`--dev`) or when the app is frozen the default browser is
opened automatically unless `--no-browser` is set or `MBFORGE_NO_BROWSER=1`
is exported.
"""

import argparse
import os
import socket
import sys
from collections.abc import Sequence

from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.__main__")


def _port_in_use(host: str, port: int) -> bool:
    """Probe whether host:port is already bound (any process, any platform)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1" if host == "localhost" else host, port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def _replace_existing(host: str, port: int) -> None:
    """Use the process governance layer to find and reap blocking orphans.

    This replaces the old ``_close_existing_listener`` which killed *any*
    python.exe on the target port. Now we only terminate processes that pass
    the strict A1-A5/B1-B2 criteria (registry-confirmed MBForge instances
    holding the queue lock or listening on our port).
    """
    from .infra.process import find_orphans, reap
    from .utils.config import load_global_config

    cfg = load_global_config()
    library_root = cfg.library_root
    if library_root is None:
        logger.warning(
            "No library root configured; cannot auto-reap orphans for port %d", port
        )
        return

    orphans = find_orphans(library_root, port)
    blocking = [o for o in orphans if o.blocking]

    if not blocking:
        logger.info("No blocking orphans found for port %d", port)
        return

    logger.info("Reaping %d blocking orphan(s) for port %d...", len(blocking), port)
    for candidate in blocking:
        result = reap(candidate, dry_run=False, grace=5.0)
        logger.info("  PID %d: %s — %s", candidate.pid, result.action, result.reason)


def _run_doctor(options) -> None:
    """Run the diagnostic doctor command."""
    import json as _json

    from .infra.process import (
        ProcessRegistry,
        find_orphans,
        port_listeners,
        read_lock_holder,
    )
    from .utils.config import load_global_config

    library_root = options.library_root
    if library_root is None:
        cfg = load_global_config()
        library_root = cfg.library_root
    if library_root is None:
        print("Error: no library root configured. Use --library-root.", file=sys.stderr)
        sys.exit(1)

    port = options.port
    registry = ProcessRegistry.get(library_root)

    # Gather diagnostics
    lock_holder = read_lock_holder(library_root)
    listeners = port_listeners(port)
    orphans = find_orphans(library_root, port)

    registered = registry.all_identities()
    stale = registry.sweep_stale()

    output = {
        "library_root": str(library_root),
        "port": port,
        "lock_holder": {
            "pid": lock_holder.pid if lock_holder else None,
            "host": lock_holder.host if lock_holder else None,
            "role": lock_holder.role if lock_holder else None,
            "legacy": lock_holder.legacy if lock_holder else None,
        }
        if lock_holder
        else None,
        "port_listeners": listeners,
        "registered_processes": [
            {
                "pid": r.pid,
                "ppid": r.ppid,
                "role": r.role,
                "heartbeat_at": r.heartbeat_at,
                "alive": _pid_alive_simple(r.pid),
            }
            for r in registered
        ],
        "stale_removed": [{"pid": s.pid, "role": s.role} for s in stale],
        "orphans": [
            {
                "pid": o.pid,
                "confidence": o.confidence,
                "blocking": o.blocking,
                "reason": o.reason,
                "cmdline": o.identity.cmdline[:200],
            }
            for o in orphans
        ],
    }

    if options.json:
        print(_json.dumps(output, indent=2))
        return

    # Human-readable output
    print(f"Library root: {library_root}")
    print(f"Port to check: {port}")
    print()

    if lock_holder:
        status = (
            "LEGACY (unknown owner)" if lock_holder.legacy else f"PID {lock_holder.pid}"
        )
        print(
            f"Lock holder: {status} (role={lock_holder.role}, host={lock_holder.host})"
        )
    else:
        print("Lock holder: none (file does not exist)")

    if listeners:
        print(f"Port {port} listeners: PIDs {listeners}")
    else:
        print(f"Port {port}: free")

    print()
    print(f"Registered processes: {len(registered)}")
    for r in registered:
        alive = "alive" if _pid_alive_simple(r.pid) else "dead"
        print(f"  PID {r.pid} role={r.role} ppid={r.ppid} [{alive}]")

    if stale:
        print(f"\nStale entries removed: {[s.pid for s in stale]}")

    print()
    blocking = [o for o in orphans if o.blocking]
    non_blocking = [o for o in orphans if not o.blocking]

    if blocking:
        print(f"Blocking orphans ({len(blocking)}):")
        for o in blocking:
            print(f"  PID {o.pid} [{o.confidence}] {o.reason}")
            print(f"    cmdline: {o.identity.cmdline[:160]}")
    else:
        print("No blocking orphans.")

    if non_blocking:
        print(f"\nNon-blocking orphans ({len(non_blocking)}, report only):")
        for o in non_blocking:
            print(f"  PID {o.pid} [{o.confidence}] {o.reason}")

    if options.fix and blocking:
        print("\nReaping blocking orphans...")
        from .infra.process import reap

        for o in blocking:
            result = reap(o, dry_run=False, grace=5.0)
            print(f"  PID {o.pid}: {result.action} — {result.reason}")
    elif options.fix and not blocking:
        print("\nNo blocking orphans to reap.")


def _pid_alive_simple(pid: int) -> bool:
    """Quick liveness check without importing the full process module."""
    import os

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main(argv: Sequence[str] | None = None) -> None:
    """Start the MBForge web application or run a diagnostic command."""
    from .utils.paths import DEFAULT_SIDECAR_PORT

    parser = argparse.ArgumentParser(description="Start the MBForge web application.")
    subparsers = parser.add_subparsers(dest="command")

    # --- doctor subcommand ---
    doctor_parser = subparsers.add_parser(
        "doctor", help="diagnose process, port, and lock state"
    )
    doctor_parser.add_argument(
        "--fix", action="store_true", help="automatically reap blocking orphans"
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="output results as JSON"
    )
    doctor_parser.add_argument(
        "--library-root",
        default=None,
        help="library root to inspect (defaults to configured root)",
    )
    doctor_parser.add_argument(
        "--port",
        type=int,
        default=os.environ.get("MBFORGE_PORT", DEFAULT_SIDECAR_PORT),
        help="port to check for listeners",
    )

    # --- legacy positional args (start server) ---
    parser.add_argument("--host", default=os.environ.get("MBFORGE_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=os.environ.get("MBFORGE_PORT", DEFAULT_SIDECAR_PORT),
    )
    parser.add_argument(
        "--dev", action="store_true", help="enable developer browser auto-open"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="disable browser auto-open"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="reload the application when Python source files change",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="stop an existing local Python listener on the requested port",
    )
    options = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    # Handle doctor subcommand
    if getattr(options, "command", None) == "doctor":
        _run_doctor(options)
        return

    # Legacy server start path
    if not 1 <= options.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    port = options.port
    host = options.host
    dev_mode = options.dev
    if options.no_browser:
        os.environ["MBFORGE_NO_BROWSER"] = "1"

    # Auto-open the browser in explicit --dev mode (developer experience:
    # don't make `mbforge --dev` require a separate tab-open step), but
    # never if MBFORGE_NO_BROWSER=1 is exported.
    _auto_browser = (
        dev_mode
        and os.environ.get("MBFORGE_NO_BROWSER") != "1"
        and host in ("127.0.0.1", "localhost", "0.0.0.0")
    )
    if _auto_browser:
        import threading
        import time
        import webbrowser

        def _open():
            time.sleep(2)
            url = f"http://127.0.0.1:{port}"
            try:
                webbrowser.open(url)
                print(f"\n>>> MBForge running at {url}\n")
            except Exception as exc:  # noqa: BLE001 — browser open is best-effort
                # Browsers on headless/CI hosts reject launching; the app still
                # serves fine, so log instead of raising or silently dropping.
                logger.warning("Could not auto-open browser: %s", exc)

        threading.Thread(target=_open, daemon=True).start()

    if options.replace_existing:
        _replace_existing(host, port)
    if _port_in_use(host, port):
        parser.error(
            f"port {port} is already in use; re-run with --replace-existing "
            "to stop the existing MBForge process"
        )

    print(f"MBForge running at http://{host}:{port}", flush=True)

    import uvicorn

    uvicorn.run(
        "mbforge.app:app",
        host=host,
        port=port,
        reload=options.reload,
        reload_dirs=["src"] if options.reload else None,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
