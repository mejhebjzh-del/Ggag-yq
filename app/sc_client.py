import abc
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

log = logging.getLogger("sc.client")

class SnapError(Exception): pass
class AuthError(SnapError): pass
class RateLimitError(SnapError): pass
class TransientError(SnapError): pass

class SnapBackend(abc.ABC):
    @abc.abstractmethod
    async def login(self) -> None: ...
    @abc.abstractmethod
    async def upload_media(self, path: Path) -> str: ...
    @abc.abstractmethod
    async def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool: ...
    @abc.abstractmethod
    async def close(self) -> None: ...

class StubBackend(SnapBackend):
    def __init__(self, username: str) -> None: self.username = username
    async def login(self) -> None: pass
    async def upload_media(self, path: Path) -> str: return f"stub-{uuid.uuid4().hex[:12]}"
    async def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool: return True
    async def close(self) -> None: pass

class PlaywrightBackend(SnapBackend):
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._lock = asyncio.Lock()
        self._is_logged_in = False

    async def _init_browser(self) -> None:
        if self.browser: return
        self.playwright = await async_playwright().start()
        
        proxy_url = os.getenv("PROXY_URL", "").strip()
        proxy = {"server": proxy_url} if proxy_url else None
        
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            proxy=proxy
        )
        
        storage_state = None
        auth_path = Path("/app/auth.json")
        if auth_path.exists():
            try:
                storage_state = json.loads(auth_path.read_text())
                log.info("Loaded session from auth.json")
            except Exception as exc:
                log.warning("Failed to load auth.json: %s", exc)

        self.context = await self.browser.new_context(
            storage_state=storage_state,
            user_agent="Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            viewport={"width": 412, "height": 915},
            is_mobile=True,
            has_touch=True
        )
        self.page = await self.context.new_page()

    async def login(self) -> None:
        async with self._lock:
            if self._is_logged_in: return
            await self._init_browser()
            log.info("Navigating to Snapchat Web for %s...", self.username)
            try:
                await self.page.goto("https://web.snapchat.com/", timeout=60000, wait_until="domcontentloaded")
                await self.page.wait_for_timeout(4000)

                if await self.page.locator('div[role="button"]:has-text("Chat"), button:has-text("Chat")').count() > 0:
                    log.info("Session valid for %s", self.username)
                    self._is_logged_in = True
                    return

                await self.page.locator('input[name="username"]').fill(self.username)
                await self.page.locator('button:has-text("Log In"), button:has-text("Next")').first.click()
                await self.page.wait_for_timeout(3000)
                
                await self.page.locator('input[name="password"]').fill(self.password)
                await self.page.locator('button:has-text("Log In"), button:has-text("Next")').first.click()
                await self.page.locator('div[role="button"]:has-text("Chat")').first.wait_for(state="visible", timeout=30000)

                state = await self.context.storage_state()
                Path("/app/auth.json").write_text(json.dumps(state))
                log.info("Login successful for %s", self.username)
                self._is_logged_in = True
            except Exception as exc:
                log.error("Login failed: %s", exc)
                raise AuthError(f"Login failed: {exc}")

    async def upload_media(self, path: Path) -> str: return str(path.absolute())

    async def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool:
        async with self._lock:
            try:
                for target in recipients:
                    await self.page.locator(f'text="{target}"').first.click(timeout=10000)
                    await self.page.wait_for_timeout(2000)
                    async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                        await self.page.locator('button[aria-label="Send a Snap"], button[aria-label="Camera"]').first.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(media_id)
                    await self.page.wait_for_timeout(3000)
                    await self.page.locator('button[aria-label="Send"], button:has-text("Send")').first.click(timeout=15000)
                    await self.page.wait_for_timeout(2000)
                return True
            except Exception as exc:
                raise TransientError(f"Send failed: {exc}")

    async def close(self) -> None:
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
