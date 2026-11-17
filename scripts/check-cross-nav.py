#!/usr/bin/env python3
"""HEAD-check every book URL linked from the landing page suite nav."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = "dseams-cross-nav-check/1.0"


def head(url: str) -> int:
    req = Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status
    except HTTPError as exc:
        return exc.code
    except URLError:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, nargs="?", default=Path("install.json"))
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures: list[str] = []
    for entry in data.get("packages", []):
        book = entry.get("book")
        if not book:
            continue
        code = head(book if book.endswith("/") else f"{book}/")
        if code < 200 or code >= 400:
            failures.append(f"{book}: HTTP {code}")
        else:
            print(f"{book}: {code}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("cross-nav: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
