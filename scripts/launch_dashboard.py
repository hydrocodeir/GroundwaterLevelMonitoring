"""Start the local dashboard, or reuse an instance that already owns its port."""
from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import socket
import sys
import threading
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser


ROOT = Path(__file__).resolve().parents[1]


def is_dashboard(url: str, timeout: float = 2) -> bool:
    # Loopback must not pass through a machine's HTTP proxy.
    opener = build_opener(ProxyHandler({}))
    try:
        request = Request(url + '/aquifer-3d', headers={'Cache-Control': 'no-cache'})
        with opener.open(request, timeout=timeout) as response:
            html = response.read(2_000_000).decode('utf-8', errors='replace')
            return response.status == 200 and 'id="aquiferSelect3d"' in html and 'js/aquifer3d.js' in html
    except (URLError, OSError, TimeoutError):
        return False


def port_is_occupied(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE or getattr(error, 'winerror', None) == 10048:
                return True
            raise
    return False


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ROOT))
    from app.settings import load_environment
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default=os.environ.get('APP_PORT', '8228'))
    parser.add_argument('--no-browser', action='store_true', help='Do not open a browser window.')
    parser.add_argument('--check', action='store_true', help='Check the port without starting a server or browser.')
    args = parser.parse_args(argv)
    try:
        port = int(args.port)
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        print('APP_PORT must be a number between 1 and 65535.', file=sys.stderr)
        return 2
    url = f'http://127.0.0.1:{port}'
    try:
        occupied = port_is_occupied(port)
    except OSError as error:
        print(f'Cannot use {url}: {error}', file=sys.stderr)
        return 2
    if occupied:
        # A simultaneous launch may have bound its socket just before startup completes.
        for attempt in range(3):
            if is_dashboard(url):
                print(f'Dashboard is already running at {url}')
                print('Using the existing dashboard. No second server was started.')
                if not args.no_browser and not args.check:
                    webbrowser.open(url + '/aquifer-3d')
                return 0
            if attempt < 2:
                threading.Event().wait(0.3)
        print(f'Port {port} is in use, but the dashboard could not be confirmed at {url}.', file=sys.stderr)
        print('No process was stopped. Close the other application or set APP_PORT in .env to a free port.', file=sys.stderr)
        return 2
    if args.check:
        print(f'Port {port} is available.')
        return 0

    import uvicorn
    print(f'Starting dashboard at {url}', flush=True)
    stop = threading.Event()
    if not args.no_browser:
        def open_when_ready():
            for _ in range(50):
                if stop.is_set():
                    return
                if is_dashboard(url, timeout=0.5):
                    webbrowser.open(url)
                    return
                if stop.wait(0.2):
                    return
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        uvicorn.run('app.main:app', host='127.0.0.1', port=port)
    finally:
        stop.set()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
