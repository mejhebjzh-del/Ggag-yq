"""Snapchat client adapter using Playwright web automation."""
import abc
import asyncio
import logging
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
    def __init__(self, username: str) -> None:
        self.username = username

    async def login(self) -> None:
        pass

    async def upload_media(self, path: Path) -> str:
        return f"stub-{uuid.uuid4().hex[:12]}"

    async def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool:
        return True

    async def close(self) -> None:
        pass


class PlaywrightBackend(SnapBackend):
    """Real Snapchat Web backend using Playwright Chromium."""

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
        if self.browser:
            return
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        self.page = await self.context.new_page()

    async def login(self) -> None:
        async with self._lock:
            if self._is_logged_in:
                return
            await self._init_browser()
            log.info(f"Navigating to Snapchat Web for {self.username}...")
            try:
                await self.page.goto("https://web.snapchat.com/", timeout=60000, wait_until="domcontentloaded")
                await self.page.wait_for_timeout(3000)

                # Check if already logged in (cookie session)
                if await self.page.locator('div[role="button"]:has-text("Chat"), button:has-text("Chat")').count() > 0:
                    log.info(f"Already logged in via session: {self.username}")
                    self._is_logged_in = True
                    return

                # Username step
                user_input = self.page.locator('input[name="username"]')
                await user_input.wait_for(state="visible", timeout=20000)
                await user_input.fill(self.username)
                await self.page.locator('button:has-text("Log In"), button:has-text("Next")').first.click()
                await self.page.wait_for_timeout(3000)

                # Password step
                pass_input = self.page.locator('input[name="password"]')
                await pass_input.wait_for(state="visible", timeout=15000)
                await pass_input.fill(self.password)
                await self.page.locator('button:has-text("Log In"), button:has-text("Next")').first.click()

                # Wait for login to complete
                await self.page.locator('div[role="button"]:has-text("Chat"), button:has-text("Chat")').first.wait_for(state="visible", timeout=30000)
                log.info(f"Login successful for {self.username}")
                self._is_logged_in = True

            except PWTimeout as exc:
                log.error(f"Timeout during login for {self.username}: {exc}")
                raise AuthError(f"Login timeout, likely checkpoint or bad credentials: {exc}")
            except Exception as exc:
                log.error(f"Login failed for {self.username}: {exc}")
                raise AuthError(f"Playwright login failed: {exc}")

    async def upload_media(self, path: Path) -> str:
        # Playwright handles file path directly in set_files
        return str(path.absolute())

    async def send_snap(self, media_id: str, recipients: list[str], timer: int) -> bool:
        async with self._lock:
            if not recipients:
                raise TransientError("No target recipients")
            
            try:
                for target in recipients:
                    log.info(f"Sending to {target}...")
                    
                    # Search for the user
                    search_box = self.page.locator('input[placeholder*="Search"], input[type="search"]').first
                    if await search_box.is_visible():
                        await search_box.fill(target)
                        await self.page.wait_for_timeout(2000)
                        # Click the first search result
                        await self.page.locator(f'div[role="button"]:has-text("{target}"), span:text-is("{target}")').first.click(timeout=10000)
                    else:
                        # Fallback to direct click if search not visible
                        await self.page.locator(f'div[role="button"]:has-text("{target}")').first.click(timeout=10000)

                    await self.page.wait_for_timeout(2000)

                    # Click Camera / Send button to open file chooser
                    async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                        # Snapchat web has different buttons for sending snaps
                        await self.page.locator('button[aria-label="Send a Snap"], button[aria-label="Camera"], div[role="button"][aria-label="Camera"]').first.click()
                    
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(media_id)
                    
                    # Wait for image to process and Send button to be enabled
                    await self.page.wait_for_timeout(3000)
                    await self.page.locator('button[aria-label="Send"], button:has-text("Send")').first.click(timeout=15000)
                    await self.page.wait_for_timeout(2000)
                    
                return True
            except Exception as exc:
                log.error(f"Send failed: {exc}")
                raise TransientError(f"Send failed: {exc}")

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
