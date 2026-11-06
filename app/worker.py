import asyncio
import logging
import random
import time
from .config import AppCfg
from .media_store import MediaStore
from .metrics import Metrics
from .sc_client import AuthError, RateLimitError, SnapBackend, TransientError

log = logging.getLogger("sc.worker")

class AccountWorker:
    def __init__(self, backend: SnapBackend, targets: list[str], media: MediaStore, cfg: AppCfg, metrics: Metrics, account_key: str) -> None:
        self.backend = backend
        self.targets = targets
        self.media = media
        self.cfg = cfg
        self.metrics = metrics
        self.account_key = account_key
        self._retries = 0

    async def _sleep(self, stop: asyncio.Event, seconds: float) -> None:
        if seconds <= 0: return
        try: await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError: pass

    async def _login_with_retry(self, stop: asyncio.Event) -> bool:
        backoff = self.cfg.send.backoff_base_ms / 1000.0
        backoff_max = self.cfg.send.backoff_max_ms / 1000.0
        attempts = 0
        while not stop.is_set():
            try:
                await self.backend.login()
                self.metrics.incr(self.account_key, "login_ok")
                log.info("login ok: %s", self.account_key)
                return True
            except AuthError as exc:
                self.metrics.incr(self.account_key, "auth_fail")
                log.error("login rejected for %s: %s", self.account_key, exc)
                return False
            except (RateLimitError, TransientError) as exc:
                attempts += 1
                log.warning("login retry #%d for %s: %s — backoff %.1fs", attempts, self.account_key, exc, backoff)
                await self._sleep(stop, backoff + random.uniform(0, 1.0))
                backoff = min(backoff * 2, backoff_max)
        return False

    async def run(self, stop: asyncio.Event) -> None:
        if not await self._login_with_retry(stop): return
        send = self.cfg.send
        backoff = send.backoff_base_ms / 1000.0
        backoff_max = send.backoff_max_ms / 1000.0
        min_delay = send.min_delay_ms / 1000.0
        max_delay = send.max_delay_ms / 1000.0

        while not stop.is_set():
            started = time.monotonic()
            try:
                path = self.media.next()
                media_id = await self.backend.upload_media(path)
                ok = await self.backend.send_snap(media_id, self.targets, 3)
                if not ok: raise TransientError("send_snap returned False")
                self.metrics.incr(self.account_key, "sent")
                self._retries = 0
                backoff = send.backoff_base_ms / 1000.0
            except AuthError as exc:
                self.metrics.incr(self.account_key, "auth_fail")
                log.error("auth lost for %s: %s — worker halted", self.account_key, exc)
                return
            except RateLimitError as exc:
                self.metrics.incr(self.account_key, "rate_limited")
                log.warning("rate limited %s: %s — backoff %.1fs", self.account_key, exc, backoff)
                await self._sleep(stop, backoff + random.uniform(0, 0.5))
                backoff = min(backoff * 2, backoff_max)
                continue
            except TransientError as exc:
                self._retries += 1
                self.metrics.incr(self.account_key, "transient")
                log.warning("transient error %s (%d/%d): %s", self.account_key, self._retries, send.retry_limit, exc)
                await self._sleep(stop, backoff + random.uniform(0, 0.5))
                if self._retries >= send.retry_limit:
                    self._retries = 0
                    backoff = min(backoff * 2, backoff_max)
                continue
            except FileNotFoundError as exc:
                self.metrics.incr(self.account_key, "media_missing")
                log.error("media error for %s: %s", self.account_key, exc)
                await self._sleep(stop, 5.0)
                continue
            delay = random.uniform(min_delay, max_delay)
            elapsed = time.monotonic() - started
            await self._sleep(stop, max(0.0, delay - elapsed))
        await self.backend.close()
