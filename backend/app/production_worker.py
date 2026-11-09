"""Dedicated Render Background Worker entry point; run from backend directory."""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import uuid

from .production_infrastructure import record_worker_heartbeat, run_due_jobs_once

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("tradf.production_worker")
_STOP = False


def _stop(*_):
    global _STOP
    _STOP = True


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    poll = max(2, min(60, int(os.getenv("TRADF_WORKER_POLL_SECONDS", "5"))))
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    log.info("TRADF durable worker starting; poll_seconds=%s", poll)
    try:
        record_worker_heartbeat(worker_id, status="running")
    except Exception as exc:
        log.error("Worker initial heartbeat failed: %s", type(exc).__name__)
    while not _STOP:
        did_work = False
        try:
            did_work = run_due_jobs_once(worker_id=worker_id)
        except Exception as exc:
            log.error("Worker iteration failed: %s", type(exc).__name__)
            time.sleep(min(30, poll * 2))
        try:
            record_worker_heartbeat(worker_id, status="running", did_job=did_work)
        except Exception as exc:
            log.error("Worker heartbeat failed: %s", type(exc).__name__)
        if not did_work and not _STOP:
            time.sleep(poll)
    try:
        record_worker_heartbeat(worker_id, status="stopped")
    except Exception as exc:
        log.error("Worker shutdown heartbeat failed: %s", type(exc).__name__)
    log.info("TRADF durable worker stopped")


if __name__ == "__main__":
    main()
