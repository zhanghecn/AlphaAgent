"""System endpoints: version display, update check, one-click update/restart.

Mirrors the sub2api pattern adapted to AlphaAgent's Docker-image deployment:
- version comes from APP_VERSION env (injected at image build via ARG VERSION)
- check-updates queries GitHub releases/latest and compares semver
- update/restart run whitelisted `docker compose` commands in a background
  thread (the api container gets recreated by `up`, so the work must be
  handed off to the Docker daemon and not block the response)

Auth is enforced by the Go gateway (JWT) in front of this API; every logged-in
user is the single admin. Here we only add an operation lock to prevent
concurrent update/restart and keep compose command strings fixed (no user
input concatenation) to avoid injection.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from typing import Any

from fastapi import APIRouter

from alphaagent.server.core.responses import fail, ok

router = APIRouter(prefix="/system", tags=["system"])

# --- Version (injected via ENV APP_VERSION at image build; "dev"/"source" for local)
APP_VERSION = os.environ.get("APP_VERSION", "").strip() or "dev"
BUILD_TYPE = "release" if APP_VERSION not in ("dev", "source", "") else "source"

GITHUB_REPO = os.environ.get("ALPHAAGENT_GITHUB_REPO", "zhanghecn/AlphaAgent")
# Where the deploy compose file lives on the host (api runs compose via socket).
DEPLOY_DIR = os.environ.get("ALPHAAGENT_DEPLOY_DIR", "/opt/1panel/project/AlphaAgent")
COMPOSE_FILE = os.environ.get("ALPHAAGENT_COMPOSE_FILE", "docker-compose.ghcr.yml")

# --- Operation lock: only one update/restart at a time
_op_lock = threading.Lock()
_op_name: str | None = None  # protected by _op_lock

# --- GitHub latest release cache (avoid hammering the API)
_release_cache: dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL = 300  # 5 minutes


def _parse_version(v: str) -> tuple[int, int, int]:
    """'v2.3.0-rc1' -> (2, 3, 0). Non-numeric / dev -> (0, 0, 0)."""
    v = (v or "").strip().lstrip("v")
    nums = [0, 0, 0]
    for i, part in enumerate(v.split(".")[:3]):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            nums[i] = int(digits)
    return (nums[0], nums[1], nums[2])  # type: ignore[return-value]


def _fetch_latest_release(force: bool = False) -> dict[str, Any] | None:
    """Query the latest version tag via GitHub /tags API with a 5-min cache.

    Uses /tags (not /releases/latest) because AlphaAgent pushes git tags for
    releases without creating GitHub Release objects — /releases/latest 404s.
    """
    now = time.time()
    if not force and _release_cache["data"] and now - _release_cache["ts"] < _CACHE_TTL:
        return _release_cache["data"]
    url = f"https://api.github.com/repos/{GITHUB_REPO}/tags?per_page=100"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AlphaAgent-Updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(tags, list) or not tags:
        return None
    # Pick the highest semver v* tag (filters out any non-v tags).
    v_tags = [
        t["name"]
        for t in tags
        if isinstance(t, dict) and (t.get("name") or "").startswith("v")
    ]
    v_tags = [t for t in v_tags if _parse_version(t) > (0, 0, 0)]
    if not v_tags:
        return None
    v_tags.sort(key=_parse_version, reverse=True)
    latest = v_tags[0]
    result = {
        "tag": latest,
        "name": latest,
        "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{latest}",
        "published_at": "",
        "body": "",
    }
    _release_cache["data"] = result
    _release_cache["ts"] = now
    return result


def _try_start_op(name: str) -> bool:
    global _op_name
    with _op_lock:
        if _op_name:
            return False
        _op_name = name
        return True


def _finish_op() -> None:
    global _op_name
    with _op_lock:
        _op_name = None


def _current_op() -> str | None:
    with _op_lock:
        return _op_name


# 一次性容器跑 compose：避免 api 自己跑 `up` 重建自己时被 stop 杀掉中断(self-update 自杀)。
COMPOSE_RUNNER_IMAGE = os.environ.get("ALPHAAGENT_COMPOSE_IMAGE", "docker:27-cli")


def _run_compose(args: list[str], timeout: int = 900) -> tuple[bool, str]:
    """Run a whitelisted `docker compose` via a short-lived throwaway container.

    Critical: compose must NOT run inside the api container itself, because
    `up` recreates the api container and would kill the compose process mid-
    update (self-update suicide → api exits). Instead we launch a throwaway
    container (docker:27-cli) that talks to the host daemon over the socket;
    it survives the api recreation and finishes the deploy. Args are fixed
    (never concatenated from user input) to prevent injection.
    """
    cmd = [
        "docker", "run", "--rm",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{DEPLOY_DIR}:{DEPLOY_DIR}",
        "-w", DEPLOY_DIR,
        COMPOSE_RUNNER_IMAGE,
        "compose", "-f", COMPOSE_FILE, *args,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output[-2000:]
    except FileNotFoundError:
        return False, "docker CLI not found in api image"
    except subprocess.TimeoutExpired:
        return False, f"compose {' '.join(args)} timed out"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{type(exc).__name__}: {exc}"


@router.get("/version")
def version() -> dict[str, Any]:
    """Current app version + build type (release/source)."""
    return ok({"current": APP_VERSION, "build_type": BUILD_TYPE})


@router.get("/check-updates")
def check_updates(force: bool = False) -> dict[str, Any]:
    """Compare current version with GitHub latest release."""
    release = _fetch_latest_release(force=force)
    if not release or not release.get("tag"):
        return ok({
            "current": APP_VERSION,
            "build_type": BUILD_TYPE,
            "latest": None,
            "has_update": False,
            "release_info": None,
            "error": "无法获取 GitHub 最新版本（网络或限流）",
        })
    has_update = _parse_version(release["tag"]) > _parse_version(APP_VERSION)
    return ok({
        "current": APP_VERSION,
        "build_type": BUILD_TYPE,
        "latest": release["tag"],
        "has_update": has_update,
        "release_info": release,
    })


@router.post("/update")
def perform_update() -> dict[str, Any]:
    """Trigger `docker compose pull && up -d` in background (self-update).

    Returns immediately; the api container will be recreated by `up`, so the
    frontend polls /api/system/version to detect the new version once back up.
    """
    if BUILD_TYPE != "release":
        return fail("SOURCE_BUILD", "源码构建请用 git pull 更新，不支持在线更新", {})
    if not _try_start_op("update"):
        return fail("SYSTEM_BUSY", f"已有操作进行中：{_current_op()}", {})
    if not os.path.exists("/var/run/docker.sock"):
        _finish_op()
        return fail("NO_DOCKER_SOCKET", "api 容器未挂载 docker.sock，无法在线更新", {})

    def _bg() -> None:
        try:
            _run_compose(["pull"], timeout=900)
            _run_compose(["up", "-d"], timeout=300)
        finally:
            _finish_op()

    threading.Thread(target=_bg, daemon=True, name="system-update").start()
    return ok({"message": "更新已触发，正在后台拉取镜像并重启", "need_restart": False})


@router.post("/restart")
def restart_service() -> dict[str, Any]:
    """Restart the api container via `docker compose restart alphaagent-api`."""
    if not _try_start_op("restart"):
        return fail("SYSTEM_BUSY", f"已有操作进行中：{_current_op()}", {})
    if not os.path.exists("/var/run/docker.sock"):
        _finish_op()
        return fail("NO_DOCKER_SOCKET", "api 容器未挂载 docker.sock，无法重启", {})

    def _bg() -> None:
        try:
            _run_compose(["restart", "alphaagent-api"], timeout=120)
        finally:
            _finish_op()

    threading.Thread(target=_bg, daemon=True, name="system-restart").start()
    return ok({"message": "重启已触发"})
