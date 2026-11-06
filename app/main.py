import asyncio
import logging
import signal
import sys

from aiohttp import ClientSession, web

from .config import load_config
from .logging_setup import setup_logging
from .media_store import MediaStore
from .metrics import Metrics
from .sc_client import make_backend
from .worker import AccountWorker

log = logging.getLogger("sc.main")


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def _build_web_app(metrics: Metrics) -> web.Application:
    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_get("/metrics", lambda r: web.json_response(metrics.snapshot()))
    return app


async def _self_ping_loop(
    url: str, interval: int, stop: asyncio.Event
) -> None:
    if not url:
        return
    async with ClientSession() as session:
        while not stop.is_set():
            try:
                async with session.get(url, timeout=10) as resp:
                    log.info("self-ping %s -> %s", url, resp.status)
            except Exception as exc:  # noqa: BLE001 — ping failure never fatal
                log.warning("self-ping failed: %s", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


async def _run() -> None:
    setup_logging()
    cfg = load_config()
    metrics = Metrics()
    media = MediaStore(
        cfg.media.dir,
        cfg.media.allowed_ext,
        generate_black_if_empty=cfg.media.generate_black_if_empty,
    )

    log.info(
        "boot: media=%d accounts=%d targets=%s backend=%s workers_per_account=%d",
        len(media), len(cfg.accounts), cfg.targets,
        cfg.backend, cfg.send.workers_per_account,
    )

    stop = asyncio.Event()

    def _shutdown(*_args) -> None:
        log.info("shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    workers = []
    for acct in cfg.accounts:
        for idx in range(cfg.send.workers_per_account):
            backend = make_backend(cfg.backend, acct.username, acct.password)
            key = f"{acct.username}#w{idx}"
            workers.append(
                AccountWorker(
                    backend=backend,
                    targets=cfg.targets,
                    media=media,
                    cfg=cfg,
                    metrics=metrics,
                    account_key=key,
                )
            )

    runner = web.AppRunner(_build_web_app(metrics))
    await runner.setup()
    site = web.TCPSite(runner, cfg.web.host, cfg.web.port)
    await site.start()
    log.info("http server listening on %s:%d", cfg.web.host, cfg.web.port)

    tasks = [asyncio.create_task(w.run(stop), name=w.account_key) for w in workers]
    tasks.append(
        asyncio.create_task(
            _self_ping_loop(cfg.web.self_ping_url, cfg.web.self_ping_interval_s, stop),
            name="self-ping",
        )
    )

    await stop.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.cleanup()
    log.info("shutdown complete")


def main() -> None:
    try:
        asyncio.run(_run())
    except Exception:
        logging.getLogger("sc.main").exception("fatal")
        sys.exit(1)


if __name__ == "__main__":
    main()
