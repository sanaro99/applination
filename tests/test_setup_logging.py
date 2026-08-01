"""setup_logging() must actually write to the day's log file even when the
root logger already has handlers (the uvicorn/web-server case), where
logging.basicConfig() is a no-op. Regression for empty run_<date>.log files.
"""
import logging
import os
from datetime import date

import src.main as main
from src.main import setup_logging


def test_file_handler_attaches_and_writes_when_root_already_has_handlers(tmp_path, monkeypatch):
    # Redirect the log directory into an isolated temp dir. setup_logging()
    # derives its path from src.main.ROOT at call time, so patching ROOT keeps
    # the test from writing its marker into the REAL logs/run_<today>.log (which
    # otherwise pollutes the day's production run log with test records).
    monkeypatch.setattr(main, "ROOT", tmp_path)
    log_path = tmp_path / "logs" / f"run_{date.today().isoformat()}.log"

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        # Simulate uvicorn: root already has a handler, so basicConfig would
        # silently do nothing (the original bug).
        root.handlers[:] = [logging.NullHandler()]

        setup_logging()

        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1, "exactly one day-file handler expected"
        assert os.path.basename(file_handlers[0].baseFilename).startswith("run_")

        # It must actually write module-logger records (e.g. providers) to disk.
        marker = "SETUP_LOGGING_MARKER_9f3a"
        logging.getLogger("src.providers.base").info(marker)
        for h in file_handlers:
            h.flush()
        assert marker in log_path.read_text(encoding="utf-8")

        # Idempotent: a second call (server calls this per run) must not add a
        # duplicate file handler.
        setup_logging()
        assert len([h for h in root.handlers if isinstance(h, logging.FileHandler)]) == 1
    finally:
        for h in root.handlers:
            if isinstance(h, logging.FileHandler):
                h.close()
        root.handlers[:] = saved_handlers
        root.level = saved_level
