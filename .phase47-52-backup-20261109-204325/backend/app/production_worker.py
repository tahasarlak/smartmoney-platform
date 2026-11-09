"""Dedicated Render Background Worker entry point; run from backend directory."""
from __future__ import annotations
import logging
import os
import signal
import time
from .production_infrastructure import run_due_jobs_once

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("tradf.production_worker")
_STOP=False

def _stop(*_):
    global _STOP
    _STOP=True

def main():
    signal.signal(signal.SIGTERM,_stop)
    signal.signal(signal.SIGINT,_stop)
    poll=max(2,int(os.getenv("TRADF_WORKER_POLL_SECONDS","5")))
    log.info("TRADF durable worker starting; poll_seconds=%s",poll)
    while not _STOP:
        try:
            did_work=run_due_jobs_once()
            if not did_work: time.sleep(poll)
        except Exception:
            # Never log job payloads, API keys, or database URLs.
            log.error("Worker iteration failed: %s",type(__import__("sys").exc_info()[1]).__name__)
            time.sleep(min(30,poll*2))
    log.info("TRADF durable worker stopped")

if __name__=="__main__":
    main()
