"""In-process job queue for slow background work (conversion, sending, import).

A single worker thread runs submitted callables and tracks their status and
progress so callers can poll instead of blocking a request.
"""
