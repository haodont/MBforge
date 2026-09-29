"""Pipeline-domain services.

- :mod:`ingest` — thin use-case facade over the infra ingest executor
  (enqueue / batch actions / worker status / SSE event stream).
- :mod:`detection_cache` — ``molecule_detections`` table access.
"""
