"""Snapchat client adapter.

The worker engine depends only on the SnapBackend protocol. Two backends:
  - PysnapBackend : real Snapchat private API via the `pysnap` package.
  - StubBackend   : in-memory backend, used to verify the engine offline.

Swapping the underlying library never touches orchestration code.
"""
import abc
import logging
import uuid
from pathlib import Path

log = logging.getLogger("sc.client")


class SnapError(Exception):
    """Base class for all Snapchat client errors."""


class AuthError(SnapError):
    """Login rejected: bad credentials, checkpoint, 2FA."""


class RateLimitError(SnapError):
    """Server signalled throttling; caller must back off."""


class TransientError(SnapError):
    """Network / 5xx / unexpected response; safe to retry with backoff."""


class SnapBackend(abc.ABC):
    @abc.abstractmethod
    def login(self) -> None: ...

    @abc.abstractmethod
    def upload_media(self, path: Path) -> str: ...

    @abc.abstractmethod
    def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool: ...

    @abc.abstractmethod
    def close(self) -> None: ...


class StubBackend(SnapBackend):
    """Offline backend used for engine verification."""

    def __init__(self, username: str) -> None:
        self.username = username
        self._logged_in = False

    def login(self) -> None:
        self._logged_in = True

    def upload_media(self, path: Path) -> str:
        return f"stub-{uuid.uuid4().hex[:12]}"

    def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool:
        return True

    def close(self) -> None:
        self._logged_in = False


class PysnapBackend(SnapBackend):
    """Real Snapchat private API backend."""

    def __init__(self, username: str, password: str, proxy: str | None = None) -> None:
        try:
            import pysnap  # imported lazily so stub mode works without it
        except ImportError as exc:
            raise SnapError(
                "pysnap is not installed; install requirements.txt"
            ) from exc

        self.username = username
        self.password = password
        self._sc = pysnap.Snapchat(proxy=proxy) if proxy else pysnap.Snapchat()

    def _classify(self, exc: Exception) -> SnapError:
        msg = str(exc).lower()
        if any(k in msg for k in ("password", "credential", "checkpoint", "twofactor")):
            return AuthError(str(exc))
        if any(k in msg for k in ("rate", "429", "too many")):
            return RateLimitError(str(exc))
        return TransientError(str(exc))

    def login(self) -> None:
        try:
            self._sc.login(self.username, self.password)
        except Exception as exc:  # noqa: BLE001 — surface as SnapError
            raise self._classify(exc) from exc

    def upload_media(self, path: Path) -> str:
        try:
            media_id = self._sc.upload_media(str(path))
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc
        if not media_id:
            raise TransientError("upload_media returned empty media id")
        return str(media_id)

    def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool:
        try:
            return bool(self._sc.send_snap(media_id, recipients, timer))
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc

    def close(self) -> None:
        try:
            self._sc.logout()
        except Exception:  # noqa: BLE001 — best-effort logout
            pass


def make_backend(kind: str, username: str, password: str) -> SnapBackend:
    kind = (kind or "pysnap").lower()
    if kind == "stub":
        return StubBackend(username)
    if kind == "pysnap":
        return PysnapBackend(username, password)
    raise ValueError(f"unknown backend: {kind}")
