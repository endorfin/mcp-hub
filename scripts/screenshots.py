# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render the README screenshots and the social preview from example data.

Run with `uv run scripts/screenshots.py`. Starts a hub on a free port with an
empty temporary home and feeds the interface the example data in
screenshot-data.json, so no MCP server is started and nothing leaves the machine.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = json.loads((ROOT / "scripts" / "screenshot-data.json").read_text())
SHOT = {"width": 1200, "height": 832}
FRAME_PALETTES = """
showTab("settings");
document.querySelector("#settingsNav [data-sec=ui]").click();
const stage = document.createElement("div");
stage.id = "paletteShot";
Object.assign(stage.style, { position: "fixed", inset: "0 auto auto 0", zIndex: 2147483647, padding: "24px", background: "var(--bg)", width: "760px" });
const card = document.createElement("div");
card.className = "card";
card.append(Object.assign(document.createElement("b"), { textContent: document.querySelector(".palettes legend").textContent }));
const grid = document.querySelector(".palette-grid").cloneNode(true);
grid.style.marginTop = "4px";
card.append(grid);
stage.append(card);
document.body.append(stage);
for (const el of document.body.children) if (el !== stage) el.style.visibility = "hidden";
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_hub(home, port):
    (home / "gui-settings.json").write_text(json.dumps({"language": "en", "checkUpdates": False}))
    (home / "servers.json").write_text(json.dumps({"mcpServers": {}}))
    env = {**os.environ, "MCP_HUB_HOME": str(home), "PORT": str(port)}
    hub = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1)
            return hub
        except OSError:
            time.sleep(0.1)
    hub.kill()
    raise SystemExit("The hub did not start.")


def example_routes(page, theme, palette="default"):
    now = time.time()
    hub_status = {name: {"error": None, "summary": "", "prompts": 0, "resources": 0, "resourceTemplates": 0, **h}
                  for name, h in DATA["hub"].items()}
    usage = {name: {"count": count, "last": now - ago} for name, (count, ago) in DATA["usedSecondsAgo"].items()}
    snapshot = {name: {"enabled": True, "disabledTools": sorted(s.get("disabledTools", []))} for name, s in DATA["servers"].items()}

    def state(route):
        body = route.fetch().json()
        body["config"]["mcpServers"] = DATA["servers"]
        body["settings"].update(theme=theme, palette=palette, language="en")
        body["profiles"] = {"active": DATA["profile"], "profiles": {DATA["profile"]: snapshot}}
        route.fulfill(json=body)

    page.route("**/api/state", state)
    page.route("**/api/hub", lambda route: route.fulfill(json=hub_status))
    page.route("**/api/usage", lambda route: route.fulfill(json=usage))
    page.route("**/api/live", lambda route: route.fulfill(json=DATA["liveClients"]))


def open_hub(browser, port, scheme, theme="auto", palette="default"):
    page = browser.new_page(viewport=SHOT, device_scale_factor=2, color_scheme=scheme, locale="en-US")
    example_routes(page, theme, palette)
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector("#statusText:has-text('clients')", timeout=20000)
    page.wait_for_timeout(300)
    return page


def main():
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="mcp-hub-screenshots-") as tmp:
        hub = start_hub(Path(tmp), port)
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(channel="chrome")
                except Exception:
                    browser = p.chromium.launch()
                for scheme in ("light", "dark"):
                    page = open_hub(browser, port, scheme)
                    page.screenshot(path=DOCS / f"screenshot-{scheme}.png")
                    page.evaluate(FRAME_PALETTES)
                    page.wait_for_timeout(200)
                    page.locator("#paletteShot").screenshot(path=DOCS / f"color-schemes-{scheme}.png")
                    page.close()
                page = browser.new_page(viewport={"width": 1280, "height": 640})
                page.goto((ROOT / "scripts" / "social-preview.html").as_uri())
                page.wait_for_load_state("networkidle")
                page.screenshot(path=DOCS / "social-preview.png")
                browser.close()
        finally:
            hub.terminate()
            hub.wait()
    for name in ("screenshot-light", "screenshot-dark", "color-schemes-light", "color-schemes-dark", "social-preview"):
        print(DOCS / f"{name}.png")


if __name__ == "__main__":
    main()
