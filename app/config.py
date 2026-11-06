import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class AccountCfg:
    username: str
    password: str


@dataclass
class SendCfg:
    workers_per_account: int = 2
    min_delay_ms: int = 800
    max_delay_ms: int = 2000
    retry_limit: int = 5
    backoff_base_ms: int = 1000
    backoff_max_ms: int = 60000


@dataclass
class MediaCfg:
    dir: str = "./media"
    allowed_ext: List[str] = field(
        default_factory=lambda: [".jpg", ".jpeg", ".png"]
    )
    generate_black_if_empty: bool = True


@dataclass
class WebCfg:
    host: str = "0.0.0.0"
    port: int = 8080
    self_ping_url: str = ""
    self_ping_interval_s: int = 300


@dataclass
class AppCfg:
    accounts: List[AccountCfg]
    targets: List[str]
    send: SendCfg
    media: MediaCfg
    web: WebCfg
    backend: str = "pysnap"


def _read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(path: Optional[str] = None) -> AppCfg:
    cfg_path = Path(path or os.getenv("CONFIG_PATH", "config.yaml"))
    data = _read_yaml(cfg_path) if cfg_path.exists() else {}

    accounts: List[AccountCfg] = []
    for item in data.get("accounts", []) or []:
        u = item.get("username")
        p = item.get("password")
        if u and p:
            accounts.append(AccountCfg(username=u, password=p))

    env_u = os.getenv("SC_USERNAME")
    env_p = os.getenv("SC_PASSWORD")
    if env_u and env_p and not accounts:
        accounts.append(AccountCfg(username=env_u, password=env_p))

    if not accounts:
        raise ValueError(
            "no accounts configured (config.yaml accounts[] or SC_USERNAME/SC_PASSWORD)"
        )

    targets: List[str] = []
    for t in data.get("targets", []) or []:
        if isinstance(t, str) and t.strip():
            targets.append(t.strip())
    if not targets:
        env_targets = os.getenv("SC_TARGETS", "")
        targets = [t.strip() for t in env_targets.split(",") if t.strip()]
    if not targets:
        raise ValueError("targets[] is required (config.yaml or SC_TARGETS)")

    send_data = data.get("send") or {}
    media_data = data.get("media") or {}
    web_data = data.get("web") or {}

    return AppCfg(
        accounts=accounts,
        targets=targets,
        send=SendCfg(**send_data),
        media=MediaCfg(**media_data),
        web=WebCfg(**web_data),
        backend=os.getenv("SC_BACKEND", data.get("backend", "pysnap")),
    )
