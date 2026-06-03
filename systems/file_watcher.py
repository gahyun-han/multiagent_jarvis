"""
File watcher — monitors Jarvis .py files and restarts jarvis.bot on change.
Uses watchdog for filesystem events with a 3s debounce to batch rapid edits.
"""
import logging
import subprocess
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WATCH_DIRS = ["agents", "orchestrator", "systems"]
DEBOUNCE_SECONDS = 3
BOT_LABEL = "jarvis.bot"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watcher] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def restart_bot(trigger_path: str):
    logger.info(f"변경 감지: {trigger_path} → jarvis.bot 재시작")
    import os
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{uid}/{BOT_LABEL}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info("jarvis.bot 재시작 완료")
    else:
        logger.error(f"재시작 실패: {result.stderr.strip()}")


class DebounceHandler(FileSystemEventHandler):
    def __init__(self):
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._last_path = ""

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            self._schedule(event.src_path)

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            self._schedule(event.src_path)

    def _schedule(self, path: str):
        # __pycache__ 와 test 파일은 무시
        if "__pycache__" in path or "/tests/" in path:
            return

        rel = Path(path).relative_to(PROJECT_ROOT) if PROJECT_ROOT in Path(path).parents else path
        logger.info(f"변경 감지 (대기 중): {rel}")

        with self._lock:
            self._last_path = str(rel)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(
                DEBOUNCE_SECONDS,
                restart_bot,
                args=[self._last_path],
            )
            self._timer.start()


def main():
    handler = DebounceHandler()
    observer = Observer()

    for d in WATCH_DIRS:
        watch_path = PROJECT_ROOT / d
        if watch_path.exists():
            observer.schedule(handler, str(watch_path), recursive=True)
            logger.info(f"감시 시작: {watch_path}")

    observer.start()
    logger.info(f"Jarvis 파일 감시 중 (디바운스: {DEBOUNCE_SECONDS}s)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
