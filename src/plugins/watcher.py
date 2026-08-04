"""Local filesystem hot-reload.

Tools are served exclusively from a local directory (no remote file share of
any kind). This watcher observes that directory for out-of-band edits
(create/modify/delete) and enqueues reload events for the drain loop in
``app.py`` to apply.
"""
from __future__ import annotations

import contextlib
import queue
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class ToolDirectoryWatcher(FileSystemEventHandler):
    """Watches the local tools dir for edits; enqueues reload events."""

    def __init__(self, reload_q: "queue.Queue", tools_dir: Path):
        self.q = reload_q
        self.tools_dir = tools_dir
        self.observer = Observer()

    def _emit(self, src_path: str, action: str) -> None:
        p = Path(src_path)
        if p.suffix == ".py" and p.name != "__init__.py":
            self.q.put((action, str(p)))

    def on_created(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "load")

    def on_modified(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "load")

    def on_deleted(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "unload")

    def start(self):
        self.observer.schedule(self, str(self.tools_dir.resolve()), recursive=False)
        self.observer.start()

    def stop(self):
        with contextlib.suppress(Exception):
            self.observer.stop()
            self.observer.join(timeout=5)
