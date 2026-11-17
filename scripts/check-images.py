#!/usr/bin/env python3
"""Check images and Output block overflow in a real browser at target widths."""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import socket
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VIEWPORTS = (
    ("desktop", 1440, 2200),
    ("tablet", 768, 2200),
    ("mobile", 390, 2200),
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(site: Path, port: int) -> ThreadingHTTPServer:
    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(site), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def probe_playwright(url: str, width: int, height: int) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="load", timeout=60_000)
            page.wait_for_timeout(300)
            return page.evaluate(
                """() => {
                    const output = document.querySelector("#output");
                    const card = output.querySelector(".specimen-code");
                    const pre = card.querySelector(".code-box");
                    return {
                        images: [...document.images].map((img) => ({
                            src: img.currentSrc || img.src,
                            alt: img.alt,
                            naturalWidth: img.naturalWidth,
                            naturalHeight: img.naturalHeight,
                            loading: img.loading,
                        })),
                        output: {
                            sectionClientWidth: output.clientWidth,
                            sectionScrollWidth: output.scrollWidth,
                            cardClientWidth: card.clientWidth,
                            cardScrollWidth: card.scrollWidth,
                            preClientWidth: pre.clientWidth,
                            preScrollWidth: pre.scrollWidth,
                        },
                    };
                }"""
            )
        finally:
            browser.close()


def probe_node_playwright(url: str, width: int, height: int) -> dict:
    pw_path = "/tmp/pw/node_modules/playwright-core"
    chrome = shutil.which("google-chrome") or "/usr/local/bin/google-chrome"
    script = f"""
const {{ chromium }} = require({json.dumps(pw_path)});
(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(chrome)},
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"]
  }});
  try {{
    const page = await browser.newPage({{ viewport: {{ width: {width}, height: {height} }} }});
    await page.goto({json.dumps(url)}, {{ waitUntil: "load", timeout: 60000 }});
    await page.waitForTimeout(300);
    const result = await page.evaluate(() => {{
      const output = document.querySelector("#output");
      const card = output.querySelector(".specimen-code");
      const pre = card.querySelector(".code-box");
      return {{
        images: [...document.images].map((img) => ({{
          src: img.currentSrc || img.src,
          alt: img.alt,
          naturalWidth: img.naturalWidth,
          naturalHeight: img.naturalHeight,
          loading: img.loading,
        }})),
        output: {{
          sectionClientWidth: output.clientWidth,
          sectionScrollWidth: output.scrollWidth,
          cardClientWidth: card.clientWidth,
          cardScrollWidth: card.scrollWidth,
          preClientWidth: pre.clientWidth,
          preScrollWidth: pre.scrollWidth,
        }},
      }};
    }});
    console.log(JSON.stringify(result));
  }} finally {{
    await browser.close();
  }}
}})();
"""
    out = subprocess.check_output(["node", "-e", script], text=True, timeout=60)
    return json.loads(out)


def probe(url: str, width: int, height: int) -> dict:
    try:
        import playwright  # noqa: F401
        return probe_playwright(url, width, height)
    except ImportError:
        return probe_node_playwright(url, width, height)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "site",
        type=Path,
        nargs="?",
        default=Path.cwd(),
        help="Site root containing index.html",
    )
    args = parser.parse_args()
    site = args.site.resolve()
    index = site / "index.html"
    if not index.is_file():
        print(f"missing {index}", file=sys.stderr)
        return 1

    port = free_port()
    server = serve(site, port)
    base = f"http://127.0.0.1:{port}/index.html"
    failures: list[str] = []
    lines: list[str] = []

    try:
        for label, width, height in VIEWPORTS:
            result = probe(base, width, height)
            images = result["images"]
            output = result["output"]
            lines.append(f"=== {label} {width}x{height}")
            for item in images:
                src = item["src"]
                short = src.rsplit("/", 1)[-1]
                nw = item["naturalWidth"]
                nh = item["naturalHeight"]
                mark = "ok" if nw > 0 and nh > 0 else "BLANK"
                lines.append(f"  {mark} {short} {nw}x{nh} loading={item['loading']!r}")
                if nw == 0 or nh == 0:
                    failures.append(f"{label}: blank image {src}")
            lines.append(
                "  output overflow "
                f"section={output['sectionScrollWidth']}/{output['sectionClientWidth']} "
                f"card={output['cardScrollWidth']}/{output['cardClientWidth']} "
                f"pre={output['preScrollWidth']}/{output['preClientWidth']}"
            )
            for element in ("section", "card", "pre"):
                scroll = output[f"{element}ScrollWidth"]
                client = output[f"{element}ClientWidth"]
                if scroll > client:
                    failures.append(
                        f"{label}: Output {element} overflows horizontally "
                        f"({scroll}px > {client}px)"
                    )
    finally:
        with contextlib.suppress(Exception):
            server.shutdown()

    print("\n".join(lines))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("image and Output overflow check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
