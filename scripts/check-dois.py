"""Resolve every doi.org link through the DOI handle API.

Publisher landings (ACS, PNAS) answer 403 to automated clients, so
lychee.toml excludes them. The handle API at doi.org answers for every
registered DOI and is what this check asks instead.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

DOI_LINK = re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s)\]>\"'`]+)")
API = "https://doi.org/api/handles/"
SUFFIXES = {".md", ".html", ".org", ".cff", ".txt"}


def collect(paths: list[Path]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for root in paths:
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in files:
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            for match in DOI_LINK.finditer(text):
                doi = match.group(1).rstrip(".,;:")
                found.setdefault(doi, []).append(str(path))
    return found


def resolve(doi: str, retries: int = 3) -> str | None:
    request = Request(API + quote(doi, safe="/"), headers={"User-Agent": "dseams-doi-check"})
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=20) as response:
                body = json.load(response)
        except HTTPError as error:
            if error.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except URLError:
            if attempt == retries - 1:
                raise
        else:
            if body.get("responseCode") != 1:
                return None
            for value in body.get("values", []):
                if value.get("type") == "URL":
                    return value["data"]["value"]
            return None
        time.sleep(2**attempt)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    found = collect(args.paths)
    if not found:
        print("no doi.org links found")
        return 1
    failures = []
    for doi, sources in sorted(found.items()):
        target = resolve(doi)
        if target is None:
            failures.append(f"{doi}: not registered ({', '.join(sorted(set(sources)))})")
        else:
            print(f"{doi} -> {target}")
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
