import threading
import time
from collections import defaultdict
from typing import Dict, Optional


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[tuple, int] = defaultdict(int)
        self._started = time.time()
        self._last_error: Optional[str] = None

    def incr(self, account: str, key: str, n: int = 1) -> None:
        with self._lock:
            self._counters[(account, key)] += n

    def set_error(self, msg: str) -> None:
        with self._lock:
            self._last_error = msg

    def snapshot(self) -> dict:
        with self._lock:
            accounts: Dict[str, Dict[str, int]] = defaultdict(dict)
            for (acct, key), value in self._counters.items():
                accounts[acct][key] = value
            return {
                "uptime_s": int(time.time() - self._started),
                "accounts": dict(accounts),
                "last_error": self._last_error,
            }
