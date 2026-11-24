"""Run the default local API inside the tray process, so it cannot outlive Quit.

An independently started API is reused, but remains under its owner's control.
Other API URLs are always treated as external services.
"""
import importlib
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse


class LocalBackend:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._server = None
        self._thread = None
        self._module = None

    @property
    def owned(self):
        return self._server is not None

    def start(self):
        if self.owned:
            return
        url = urlparse(self.base_url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
                or url.port != 8000 or url.path.rstrip("/") != "/v1"):
            return
        import httpx
        try:
            # A reachable HTTP service is external, even if it has no /health.
            # Never terminate a separately launched server or another local API.
            with httpx.Client(timeout=1.0, trust_env=False) as client:
                client.get(f"http://{url.hostname}:{url.port}/health")
            print("[npuquilly] using independently started server; its lifetime is external")
            return
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pass
        except httpx.ReadTimeout:
            print("[npuquilly] local service accepted a connection but did not respond; leaving it external")
            return
        root = Path(__file__).resolve().parents[2]
        if not (root / "server" / "server.py").is_file():
            raise RuntimeError("Local server files are missing. Start a server manually or restore server/server.py.")
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        self._module = importlib.import_module("server.server")
        import uvicorn
        self._server = uvicorn.Server(uvicorn.Config(
            self._module.app, host=url.hostname, port=url.port, log_level="info"))
        self._thread = threading.Thread(target=self._server.run,
                                        name="NpuQuilly local API", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError("Local server could not start. Check the app log or port 8000.")
            time.sleep(0.05)
        print("[npuquilly] local API runs inside the tray process; Quit releases its models")

    def unload(self):
        if self.owned:
            self._module.unload_models()

    def reconfigure(self, base_url: str, unload: bool = False):
        if base_url != self.base_url:
            self.stop()
            if self.owned:
                raise RuntimeError("The local server is still finishing a request; retry the API change shortly.")
            self.base_url = base_url
            self.start()
        elif unload:
            self.unload()

    def stop(self):
        if not self.owned:
            return
        server, thread, module = self._server, self._thread, self._module
        server.should_exit = True
        thread.join(timeout=5)
        if not thread.is_alive():
            module.unload_models()
            self._server = self._thread = self._module = None
        else:
            # This server is a daemon in the tray process, never a detached child.
            # Keep ownership if startup/shutdown is still pending.
            print("[npuquilly] local API is still finishing an active request")

    def __enter__(self):
        try:
            self.start()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, *exc):
        self.stop()
