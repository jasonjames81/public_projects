#!/usr/bin/env python3
"""In-place self-update for the Job App LLM Helper.

The launchers (start-mac.command / start.sh / start-windows.bat) call this on
startup. It checks the project's GitHub releases and, if a newer one exists,
downloads the scoped release tarball and unpacks it OVER the current install —
then strips the macOS quarantine flag so Gatekeeper never re-prompts.

Why this exists: a downloaded .zip is quarantined by macOS, so every manual
re-download forces the System Settings "Open Anyway" dance. Because the user
already approved the launcher once and it runs locally, IT can fetch and
de-quarantine the update itself — no re-download, no security dialog.

Safe to overwrite app files: this app keeps no user data in the install folder
(provider config lives in the OS config dir; the applicant profile lives in the
browser). The venv is merged into, not deleted.

Exit codes: 0 = updated (launcher should relaunch), non-zero = nothing to do or a
soft failure (launcher should just continue with the current version). Set
JALLM_NO_UPDATE=1 to skip entirely (offline / air-gapped / pinned).

Network/JSON/extraction errors are swallowed: a failed update must never stop the
app from starting.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = "jasonjames81/bkjsun_public_projects"
TAG_PREFIX = "job-app-llm-helper-v"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
_TIMEOUT = 12

HERE = Path(__file__).resolve().parent


# ---- pure helpers (unit-tested) --------------------------------------------


def parse_version(tag: str, prefix: str = TAG_PREFIX) -> tuple[int, ...] | None:
    """Turn a release tag (or bare version) into a comparable int tuple.

    'job-app-llm-helper-v0.2.5' -> (0, 2, 5); '0.2.5' -> (0, 2, 5); junk -> None.
    """
    if not tag:
        return None
    core = tag[len(prefix):] if tag.startswith(prefix) else tag
    core = core.lstrip("vV").strip()
    parts = core.split(".")
    try:
        return tuple(int(p) for p in parts) if parts and parts[0] != "" else None
    except ValueError:
        return None


def is_newer(remote: tuple[int, ...] | None, local: tuple[int, ...] | None) -> bool:
    """True only when we have a remote version that beats a known local one."""
    if remote is None:
        return False
    if local is None:
        return True
    return remote > local


def pick_latest(releases: list[dict], prefix: str = TAG_PREFIX):
    """From the releases list, pick the highest-versioned, non-draft, non-prerelease
    release whose tag matches our project prefix. Returns (tag, version, assets) or None.
    """
    best = None
    for rel in releases or []:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = rel.get("tag_name", "")
        if not tag.startswith(prefix):
            continue
        ver = parse_version(tag, prefix)
        if ver is None:
            continue
        if best is None or ver > best[1]:
            best = (tag, ver, rel.get("assets", []))
    return best


def find_tarball_url(assets: list[dict]) -> str | None:
    """The scoped release asset is a single .tar.gz; return its download URL."""
    for a in assets or []:
        name = a.get("name", "")
        if name.endswith(".tar.gz"):
            return a.get("browser_download_url")
    return None


def find_checksum_url(assets: list[dict]) -> str | None:
    """Look for a .sha256 checksum file alongside the tarball."""
    for a in assets or []:
        name = a.get("name", "")
        if name.endswith(".sha256"):
            return a.get("browser_download_url")
    return None


def local_version(install_dir: Path = HERE) -> tuple[int, ...] | None:
    try:
        return parse_version((install_dir / "VERSION").read_text().strip())
    except OSError:
        return None


def payload_root(extract_dir: Path) -> Path:
    """Release tarballs carry a single top-level 'job-app-llm-helper/' dir; return it
    if present, else the extract dir itself."""
    inner = extract_dir / "job-app-llm-helper"
    return inner if inner.is_dir() else extract_dir


# ---- side-effecting steps ---------------------------------------------------


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (fixed GitHub host)
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "job-app-llm-helper"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(resp, f)


def _copy_over(src_root: Path, dst_root: Path) -> None:
    """Copy the payload over the install dir, skipping the venv (it's rebuilt by the
    launcher) and the running selfupdate temp. Existing files are overwritten."""
    for item in src_root.iterdir():
        if item.name in ("venv", "__pycache__"):
            continue
        target = dst_root / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _dequarantine(path: Path) -> None:
    """Strip the macOS quarantine xattr so Gatekeeper won't re-prompt. No-op elsewhere."""
    if sys.platform != "darwin":
        return
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(path)],
        check=False,
        capture_output=True,
    )


def _make_executable(install_dir: Path) -> None:
    for name in ("start-mac.command", "start.sh"):
        p = install_dir / name
        if p.exists():
            p.chmod(p.stat().st_mode | 0o111)


def run() -> int:
    if os.environ.get("JALLM_NO_UPDATE", "").lower() in ("1", "true", "yes"):
        return 1
    try:
        releases = _fetch_json(RELEASES_URL)
        latest = pick_latest(releases)
        if latest is None:
            return 1
        tag, remote_ver, assets = latest
        if not is_newer(remote_ver, local_version()):
            return 1
        url = find_tarball_url(assets)
        if not url:
            return 1
        print(f"Updating to {tag} …")
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            tarball = tmpd / "update.tar.gz"
            _download(url, tarball)
            sha_url = find_checksum_url(assets)
            if sha_url:
                try:
                    sha_req = urllib.request.Request(
                        sha_url, headers={"User-Agent": "job-app-llm-helper"}
                    )
                    with urllib.request.urlopen(sha_req, timeout=_TIMEOUT) as resp:
                        sha_raw = resp.read().decode("utf-8").strip()
                    expected = sha_raw.split()[0]  # format: "hash  filename"
                    actual = hashlib.sha256(tarball.read_bytes()).hexdigest()
                    if actual != expected:
                        print(
                            f"Checksum mismatch — skipping update. "
                            f"Expected {expected[:12]}…, got {actual[:12]}…"
                        )
                        return 1
                except Exception:  # noqa: S110 — checksum optional; proceed without it on fetch failure
                    pass
            extract = tmpd / "x"
            extract.mkdir()
            with tarfile.open(tarball) as tf:
                try:
                    tf.extractall(extract, filter="data")  # 3.12+: blocks path escapes
                except TypeError:
                    tf.extractall(extract)  # noqa: S202 — trusted, checksum-verified source
            _copy_over(payload_root(extract), HERE)
        # Pin the installed version ourselves rather than trusting the tarball to
        # carry a VERSION file — otherwise a release without one would re-update on
        # every launch (download loop).
        (HERE / "VERSION").write_text(".".join(str(n) for n in remote_ver) + "\n")
        _make_executable(HERE)
        _dequarantine(HERE)
        print("Updated. Restarting…")
        return 0
    except Exception:  # noqa: BLE001 — a broken update must never block startup
        return 1


if __name__ == "__main__":
    sys.exit(run())
