#!/usr/bin/env python3
"""Verify install.json versions against live package indexes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = "dseams-landing-registry-check/1.0"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=45) as resp:
        return json.load(resp)


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def pypi_version(name: str) -> str:
    data = fetch_json(f"https://pypi.org/pypi/{name}/json")
    return str(data["info"]["version"])


def crates_version(name: str, want: str) -> bool:
    data = fetch_json(f"https://crates.io/api/v1/crates/{name}")
    versions = {v["num"] for v in data.get("versions", [])}
    return want in versions


def conda_version(name: str) -> str | None:
    try:
        data = fetch_json(f"https://api.anaconda.org/package/conda-forge/{name}")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return str(data.get("latest_version") or data.get("version"))


def cran_version(name: str) -> str | None:
    try:
        html = fetch_text(f"https://cran.r-project.org/web/packages/{name}/index.html")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    match = re.search(r"Version:</td><td>([^<]+)", html)
    return match.group(1).strip() if match else None


def luarocks_version(name: str) -> str | None:
    try:
        html = fetch_text(f"https://luarocks.org/modules/d-SEAMS/{name}")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    match = re.search(r"Version\s*:\s*([0-9.]+)", html)
    return match.group(1) if match else None


def github_release_tag(repo: str, tag: str) -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", f"https://github.com/d-SEAMS/{repo}.git"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False
    return any(line.endswith(f"refs/tags/{tag}") for line in proc.stdout.splitlines())


def check_entry(entry: dict) -> list[str]:
    failures: list[str] = []
    reg = entry["registry"]
    kind = reg["kind"]
    live = entry.get("live", False)
    want = reg.get("version", "")

    if not live:
        return failures

    try:
        if kind == "pypi":
            got = pypi_version(reg["name"])
            if got != want:
                failures.append(f"{entry['id']}: PyPI has {got}, want {want}")
        elif kind == "crates":
            if not crates_version(reg["name"], want):
                failures.append(f"{entry['id']}: crates.io missing {reg['name']} {want}")
        elif kind == "conda_forge":
            got = conda_version(reg["name"])
            if got is None:
                failures.append(f"{entry['id']}: conda-forge has no {reg['name']}")
            elif got != want:
                failures.append(f"{entry['id']}: conda-forge has {got}, want {want}")
        elif kind == "cran":
            got = cran_version(reg["name"])
            if got is None:
                failures.append(f"{entry['id']}: CRAN has no {reg['name']}")
            elif got != want:
                failures.append(f"{entry['id']}: CRAN has {got}, want {want}")
        elif kind == "luarocks":
            got = luarocks_version(reg["name"])
            if got is None:
                failures.append(f"{entry['id']}: LuaRocks has no {reg['name']}")
            elif got != want:
                failures.append(f"{entry['id']}: LuaRocks has {got}, want {want}")
        elif kind == "github_tag":
            if not github_release_tag(reg["name"], want):
                failures.append(f"{entry['id']}: no GitHub release {reg['name']} {want}")
        elif kind == "julia_github":
            failures.append(f"{entry['id']}: Julia package not in General registry yet")
        else:
            failures.append(f"{entry['id']}: unknown registry kind {kind}")
    except (HTTPError, URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"{entry['id']}: registry lookup failed: {exc}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parents[1] / "install.json",
    )
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures: list[str] = []
    for entry in data.get("packages", []):
        failures.extend(check_entry(entry))
        label = entry["id"]
        if entry.get("live"):
            print(f"{label}: live ({entry.get('version', '?')})")
        else:
            print(f"{label}: source / git ({entry.get('version', '?')})")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("registry contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
