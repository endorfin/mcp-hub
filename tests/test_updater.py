import io
import json
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import updater


class FakeGitHub(HTTPServer):
    def server_bind(self):
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def serve(routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = FakeGitHub(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def tarball(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


class VersionTest(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.newer("v0.2.0", "0.1.0"))
        self.assertTrue(updater.newer("v0.10.0", "0.9.3"))
        self.assertFalse(updater.newer("v0.1.0", "0.1.0"))
        self.assertFalse(updater.newer("nightly", "0.1.0"))
        self.assertFalse(updater.newer(None, "0.1.0"))


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def fake(self, routes):
        server, base = serve(routes)
        self.servers.append(server)
        return base

    def test_check_reports_and_caches_a_newer_release(self):
        release = {"tag_name": "v0.2.0", "body": "Notes", "html_url": "https://example.com/r"}
        base = self.fake({"/repos/endorfin/mcp-hub/releases/latest": json.dumps(release).encode()})
        status = updater.Updater(self.dir, self.dir / "state", "0.1.0", api=base).check()
        self.assertEqual((status["available"], status["latest"], status["notes"], status["error"]), (True, "v0.2.0", "Notes", None))
        cached = updater.Updater(self.dir, self.dir / "state", "0.2.0", api=base)
        self.assertEqual((cached.status()["latest"], cached.status()["available"], cached.stale()), ("v0.2.0", False, False))

    def test_failed_check_keeps_the_last_result(self):
        base = self.fake({})
        status = updater.Updater(self.dir, self.dir / "state", "0.1.0", api=base).check()
        self.assertIn("Update check failed", status["error"])
        self.assertFalse(status["available"])
        with self.assertRaisesRegex(updater.UpdateError, "No newer version"):
            updater.Updater(self.dir, self.dir / "state", "0.1.0", api=base).apply()

    def git_checkout(self):
        origin = self.dir / "origin"
        origin.mkdir()
        git(origin, "init", "-q", "-b", "main")
        (origin / "app.py").write_text("v1\n")
        git(origin, "add", ".")
        git(origin, "commit", "-qm", "one")
        git(origin, "tag", "v0.1.0")
        (origin / "app.py").write_text("v2\n")
        git(origin, "commit", "-qam", "two")
        git(origin, "tag", "v0.2.0")
        clone = self.dir / "clone"
        git(self.dir, "clone", "-q", str(origin), str(clone))
        git(clone, "reset", "-q", "--hard", "v0.1.0")
        hub = updater.Updater(clone, self.dir / "state", "0.1.0")
        hub.data = {"latest": "v0.2.0"}
        return clone, hub

    def test_git_checkout_fast_forwards_to_the_release(self):
        clone, hub = self.git_checkout()
        self.assertEqual(hub.method(), "git")
        self.assertEqual(hub.apply(), "v0.2.0")
        self.assertEqual((clone / "app.py").read_text(), "v2\n")

    def test_git_checkout_with_local_changes_is_left_alone(self):
        clone, hub = self.git_checkout()
        (clone / "app.py").write_text("mine\n")
        with self.assertRaisesRegex(updater.UpdateError, "local changes"):
            hub.apply()
        self.assertEqual((clone / "app.py").read_text(), "mine\n")

    def test_git_checkout_with_own_commits_is_left_alone(self):
        clone, hub = self.git_checkout()
        (clone / "extra.py").write_text("x\n")
        git(clone, "add", ".")
        git(clone, "commit", "-qm", "local")
        with self.assertRaisesRegex(updater.UpdateError, "not part of v0.2.0"):
            hub.apply()
        self.assertEqual((clone / "app.py").read_text(), "v1\n")

    def test_archive_install_is_replaced_by_the_release(self):
        root = self.dir / "install"
        root.mkdir()
        (root / "app.py").write_text("v1\n")
        (root / "notes.txt").write_text("keep\n")
        base = self.fake({"/tarball": tarball({"endorfin-mcp-hub-abc/app.py": "v2\n", "endorfin-mcp-hub-abc/new.py": "n\n"})})
        hub = updater.Updater(root, self.dir / "state", "0.1.0", api=base)
        hub.data = {"latest": "v0.2.0", "tarball": base + "/tarball"}
        self.assertEqual(hub.method(), "archive")
        hub.apply()
        self.assertEqual([(root / n).read_text() for n in ("app.py", "new.py", "notes.txt")], ["v2\n", "n\n", "keep\n"])

    def test_archive_with_unsafe_paths_is_rejected(self):
        root = self.dir / "install"
        root.mkdir()
        (root / "app.py").write_text("v1\n")
        base = self.fake({"/tarball": tarball({"top/app.py": "v2\n", "top/../../evil.py": "x\n"})})
        hub = updater.Updater(root, self.dir / "state", "0.1.0", api=base)
        hub.data = {"latest": "v0.2.0", "tarball": base + "/tarball"}
        with self.assertRaisesRegex(updater.UpdateError, "Unexpected entry"):
            hub.apply()
        self.assertEqual((root / "app.py").read_text(), "v1\n")
        self.assertFalse((self.dir / "evil.py").exists())


if __name__ == "__main__":
    unittest.main()
