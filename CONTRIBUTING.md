# Contributing to MCP Hub

Thanks for your interest! Bug reports, ideas and pull requests are welcome.

## Getting started

```bash
git clone https://github.com/endorfin/mcp-hub.git
cd mcp-hub
python3 app.py   # GUI: http://127.0.0.1:4747
```

Python 3.11+ is all you need. To work without touching your real configuration, point the hub at a scratch folder and a free port:

```bash
MCP_HUB_HOME=/tmp/mcp-hub-dev PORT=4800 python3 app.py
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests start their own hub with a temporary configuration, so they never touch `~/.config/mcp-hub`. Where a keychain is usable (macOS, Windows, or Linux with a Secret Service such as GNOME Keyring and `secret-tool`), they also exercise the keychain and the OAuth flow (they create and delete `mcp-hub/selftest/…` and `mcp-hub/oauth/selftest-oauth`); otherwise those tests are skipped. CI runs the suite on macOS, Ubuntu and Windows with Python 3.11 and 3.13, with a keychain on all three.

Please add or extend a test for every behavior change. `tests/dummy_server.py` is a minimal stdio MCP server, `tests/dummy_oauth_server.py` a combined OAuth provider and protected MCP server.

## Principles

These come from [PRODUCT.md](PRODUCT.md) and keep the project small:

- **No dependencies.** Standard library only, no build step, one process. A feature that needs a package probably belongs elsewhere.
- **No build step for the interface.** `index.html` holds markup and script, `app.css` the styles and `i18n.js` the translations; `app.py` serves them as they are. A new asset needs an entry in `STATIC` in `app.py`.
- **No secrets in plain text.** New features that handle credentials store them in the keychain, never in `servers.json`.
- **Changes take effect immediately.** Saving syncs the hub; clients are notified via `list_changed`.

## Code style

- Match the surrounding code: naming, structure, idioms.
- Comments are the exception. Add one only when it prevents a concrete, likely mistake; explanations of *why* a change was made belong in the commit message.
- No comments in `index.html`, `app.css` or `i18n.js` – they are shipped to the browser.
- Messages from the hub, its API and the bridge are in English; agents read them too.

## Interface

- **Design:** follow [DESIGN.md](DESIGN.md) – tokens on `:root` for light and dark, custom listboxes instead of native selects, one control height, color only with meaning.
- **Translations:** the interface is available in German and English. Every visible string goes into the `I18N` dictionary in `i18n.js` with both languages: static markup via `data-i18n` / `data-i18n-placeholder` / `data-i18n-title` / `data-i18n-aria`, dynamic text via `t("key", { vars })`. If a new backend message is shown in the interface, add a German pattern to `BACKEND_DE`.
- Check your change in the browser in both color schemes and both languages (Settings → Language).

## Commits and pull requests

- One concern per commit, imperative subject line under 72 characters. The history uses a gitmoji prefix and a type, e.g. `✨ feat: …`, `🐛 fix: …`, `📝 docs: …`.
- Describe what changed and why in the pull request, and mention how you tested it.

## Releases

The version lives in one place: `VERSION` in `version.py`. It appears in the GUI header, in the hub’s `serverInfo`, and on the landing page, where the Pages workflow stamps it at deploy time.

For a release:

1. Bump `VERSION` in `version.py`.
2. Run `uv run scripts/screenshots.py`. It renders the README screenshots, the color scheme image and the social preview in `docs/` from the example data in `scripts/screenshot-data.json`, without starting any MCP server. It uses the installed Google Chrome, or Playwright’s Chromium if there is none (`uvx playwright install chromium`).
3. Look at the images, then commit everything as `🔖 release: v<version>` and tag the commit as `v<version>`.
4. Push the commit and the tag, and publish the GitHub release with notes. Pushing `version.py` redeploys the landing page with the new version.
5. Upload `docs/social-preview.png` under Settings → General → Social preview; GitHub has no API for it.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
