import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "endorfin/mcp-hub"
INTERVAL = 12 * 3600


class UpdateError(Exception):
    pass


def parse_version(text):
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(n) for n in match.groups()) if match else None


def newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "mcp-hub"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        e.close()
        raise OSError(f"HTTP {e.code} {e.reason}") from None


class Updater:
    def __init__(self, root, state_dir, version, api=None):
        self.root = Path(root)
        self.cache = Path(state_dir) / "update.json"
        self.version = version
        self.api = (api or os.environ.get("MCP_HUB_UPDATE_API") or "https://api.github.com").rstrip("/")
        self.checking = False
        self.applying = False
        try:
            self.data = json.loads(self.cache.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def method(self):
        return "git" if (self.root / ".git").exists() else "archive"

    def stale(self):
        return time.time() - (self.data.get("checkedAt") or 0) > INTERVAL

    def status(self):
        latest = self.data.get("latest")
        return {
            "current": self.version,
            "latest": latest,
            "available": newer(latest, self.version),
            "notes": self.data.get("notes") or "",
            "url": self.data.get("url"),
            "checkedAt": self.data.get("checkedAt"),
            "error": self.data.get("error"),
            "method": self.method(),
            "checking": self.checking,
            "applying": self.applying,
        }

    def check(self):
        self.checking = True
        try:
            release = json.loads(fetch(f"{self.api}/repos/{REPO}/releases/latest"))
            self.data = {
                "latest": release["tag_name"],
                "notes": release.get("body") or "",
                "url": release.get("html_url"),
                "tarball": release.get("tarball_url"),
                "checkedAt": time.time(),
            }
        except (OSError, ValueError, KeyError) as e:
            self.data = {**self.data, "checkedAt": time.time(), "error": f"Update check failed: {e}"}
        finally:
            self.checking = False
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(json.dumps(self.data))
        return self.status()

    def check_in_background(self):
        if not self.checking:
            self.checking = True
            threading.Thread(target=self.check, daemon=True).start()

    def apply(self):
        latest = self.data.get("latest")
        if not newer(latest, self.version):
            raise UpdateError("No newer version available")
        self.applying = True
        try:
            if self.method() == "git":
                self._apply_git(latest)
            else:
                self._apply_archive(latest)
        finally:
            self.applying = False
        return latest

    def _git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise UpdateError(f"git {args[0]} failed: {(result.stderr or result.stdout).strip()}")
        return result.stdout.strip()

    def _apply_git(self, tag):
        if self._git("status", "--porcelain", "--untracked-files=no"):
            raise UpdateError("The checkout has local changes; update it yourself with git")
        self._git("fetch", "--quiet", "--tags", "origin")
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", tag], cwd=self.root,
                                  capture_output=True, timeout=30)
        if ancestor.returncode:
            raise UpdateError(f"The checkout has commits that are not part of {tag}; update it yourself with git")
        if self._git("rev-parse", "--abbrev-ref", "HEAD") == "HEAD":
            self._git("checkout", "--quiet", tag)
        else:
            self._git("merge", "--quiet", "--ff-only", tag)

    def _apply_archive(self, tag):
        url = self.data.get("tarball") or f"{self.api}/repos/{REPO}/tarball/{tag}"
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "release.tar.gz"
            try:
                archive.write_bytes(fetch(url, timeout=120))
            except OSError as e:
                raise UpdateError(f"Download failed: {e}")
            target = Path(tmp) / "release"
            with tarfile.open(archive) as tar:
                members = tar.getmembers()
                for member in members:
                    path = Path(member.name)
                    if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                        raise UpdateError(f"Unexpected entry in the archive: {member.name}")
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(target, members=members, filter="data")
                else:
                    tar.extractall(target, members=members)
            top = list(target.iterdir())
            if len(top) != 1 or not (top[0] / "app.py").is_file():
                raise UpdateError("The archive does not contain MCP Hub")
            shutil.copytree(top[0], self.root, dirs_exist_ok=True)
