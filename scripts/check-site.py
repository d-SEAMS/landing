"""Validate the static landing page.

Structure, local links and wording are checked offline. Current package
versions are read from each repository's latest release tag, and the
pydseamslib wheel version from PyPI, so those lookups need network access.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PageParser(HTMLParser):
    """Collect the page structure needed by the site contract."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.links: list[tuple[str, str, str]] = []
        self.text: list[str] = []
        self.title: list[str] = []
        self._in_title = False
        self.html_lang: str | None = None
        self.h1_count = 0
        self.main_ids: list[str | None] = []
        self.nav_labels: list[str | None] = []
        self.skip_targets: list[str] = []
        self.images_without_alt = 0
        self.unsafe_blank_targets: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "html":
            self.html_lang = values.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "main":
            self.main_ids.append(values.get("id"))
        elif tag == "nav":
            self.nav_labels.append(values.get("aria-label"))
        elif tag == "img" and "alt" not in values:
            self.images_without_alt += 1

        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.duplicate_ids.add(element_id)
            self.ids.add(element_id)

        classes = set((values.get("class") or "").split())
        if tag == "a" and "skip-link" in classes and values.get("href"):
            self.skip_targets.append(values["href"] or "")

        if tag == "a" and values.get("target") == "_blank":
            rel = set((values.get("rel") or "").split())
            if not {"noopener", "noreferrer"}.issubset(rel):
                self.unsafe_blank_targets.append(values.get("href") or "<missing href>")

        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value:
                self.links.append((tag, attribute, value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.text.append(value)
            if self._in_title:
                self.title.append(value)


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def resolve_target(site: Path, source: Path, raw_url: str) -> tuple[Path, str]:
    parsed = urlsplit(raw_url)
    relative = unquote(parsed.path)
    target = site / relative.removeprefix("/") if relative.startswith("/") else source.parent / relative

    if not relative:
        target = source
    elif relative.endswith("/") or target.is_dir():
        target /= "index.html"

    return target.resolve(), unquote(parsed.fragment)


def check_page(site: Path, source: Path, page: PageParser) -> list[str]:
    relative_source = source.relative_to(site)
    failures: list[str] = []
    if page.html_lang != "en":
        failures.append(f"{relative_source}: html lang must be en")
    if not page.title:
        failures.append(f"{relative_source}: title must not be empty")
    if page.h1_count != 1:
        failures.append(f"{relative_source}: expected one h1, found {page.h1_count}")
    if page.main_ids != ["main-content"]:
        failures.append(f"{relative_source}: main must have id=main-content")
    if not page.nav_labels or any(not label for label in page.nav_labels):
        failures.append(f"{relative_source}: every nav needs an aria-label")
    if "#main-content" not in page.skip_targets:
        failures.append(f"{relative_source}: missing skip link to #main-content")
    if page.images_without_alt:
        failures.append(
            f"{relative_source}: {page.images_without_alt} image(s) lack alt attributes"
        )
    if page.duplicate_ids:
        failures.append(
            f"{relative_source}: duplicate ids: {', '.join(sorted(page.duplicate_ids))}"
        )
    for href in page.unsafe_blank_targets:
        failures.append(f"{relative_source}: target=_blank lacks safe rel: {href}")
    return failures


def check_links(
    site: Path, parsed_pages: dict[Path, PageParser]
) -> list[str]:
    failures: list[str] = []
    for source, page in parsed_pages.items():
        for tag, attribute, raw_url in page.links:
            parsed = urlsplit(raw_url)
            if parsed.scheme or parsed.netloc or raw_url.startswith("//"):
                continue
            target, fragment = resolve_target(site, source, raw_url)
            try:
                target.relative_to(site)
            except ValueError:
                failures.append(
                    f"{source.relative_to(site)}: {tag} {attribute} escapes site: {raw_url}"
                )
                continue
            if not target.exists():
                failures.append(
                    f"{source.relative_to(site)}: missing {tag} {attribute}: {raw_url}"
                )
                continue
            if fragment and target.suffix == ".html":
                target_page = parsed_pages.get(target)
                if target_page is None or fragment not in target_page.ids:
                    failures.append(
                        f"{source.relative_to(site)}: missing fragment: {raw_url}"
                    )
    return failures


def href_values(page: PageParser) -> list[str]:
    return [url for _tag, attribute, url in page.links if attribute == "href"]


def has_href(hrefs: list[str], needed: str) -> bool:
    target = needed.rstrip("/")
    for url in hrefs:
        value = url.rstrip("/")
        if value == target or value.startswith(f"{target}/"):
            return True
    return False


INTERNAL_TEXT = (
    (r"\bjobs?\s*#?\d{3,}", "job id"),
    (r"\bbase\b[^.\n]{0,60}\bvs\b[^.\n]{0,60}\btip\b", "revision comparison"),
    (r"(?<![\w./-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])", "commit hash or long job number"),
    (r"\bexclusive\b", "scheduler wording"),
    (r"\b(?:todo|fixme|xxx|wip|draft)\b", "draft marker"),
    (r"\b(?:claude|chatgpt|copilot|openai|anthropic)\b", "assistant name"),
    (r"results/reference", "internal results path"),
    (r"(?<![\w/.:-])/(?:home|users|tmp|agent|workspace|opt|var|mnt)/", "absolute path"),
)


# The one long hex run the page may show: the full 40-character id of a
# release commit, written straight after the word "commit".
RELEASE_COMMIT = re.compile(r"\bcommit\s+(?:<code>)?\Z", re.IGNORECASE)


def is_release_commit(line: str, match: re.Match[str]) -> bool:
    return len(match.group(0)) == 40 and RELEASE_COMMIT.search(line[: match.start()]) is not None


def check_internal_text(site: Path) -> list[str]:
    """Keep working notes out of the files that make up the public page."""
    failures: list[str] = []
    names = ["index.html", "README.md"]
    names.extend(path.relative_to(site).as_posix() for path in sorted(site.glob("bench/*.txt")))
    for name in names:
        path = site / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in INTERNAL_TEXT:
                for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                    if label.startswith("commit hash") and is_release_commit(line, match):
                        continue
                    failures.append(
                        f"{name}:{number}: internal text ({label}): {match.group(0)}"
                    )
                    break
    return failures


_TAG = re.compile(r"v?(\d+)\.(\d+)\.(\d+)\Z")


def _version_key(tag: str) -> tuple[int, int, int] | None:
    match = _TAG.fullmatch(tag)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def latest_release_tag(repo: str) -> str:
    """Highest vX.Y.Z tag on the public d-SEAMS repository."""
    url = f"https://github.com/d-SEAMS/{repo}.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", url],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        raise RuntimeError(f"{repo}: release tag lookup failed") from None
    best_name = ""
    best_key: tuple[int, int, int] | None = None
    for line in proc.stdout.splitlines():
        ref = line.split()[-1]
        name = ref.rsplit("/", 1)[-1]
        key = _version_key(name)
        if key is not None and (best_key is None or key > best_key):
            best_key = key
            best_name = name
    if best_key is None:
        raise RuntimeError(f"{repo}: no release tag")
    return best_name


def pypi_version(project: str) -> str:
    """Version of the current PyPI release."""
    url = f"https://pypi.org/pypi/{project}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "dseams-landing-check"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        version = str(payload["info"]["version"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        raise RuntimeError(f"{project}: PyPI lookup failed") from None
    if _version_key(version) is None:
        raise RuntimeError(f"{project}: PyPI version is not X.Y.Z")
    return version


def bare_version(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def current_versions() -> dict[str, str]:
    """Versions the page has to state, from one lookup per package."""
    return {
        "seams-core": latest_release_tag("seams-core"),
        "yodaStruct": latest_release_tag("yodaStruct"),
        "dseams-plumed": latest_release_tag("dseams-plumed"),
        "dseams-rs": latest_release_tag("dseams-rs"),
        "pydseamslib": pypi_version("pydseamslib"),
    }


def check_contract(site: Path, index: PageParser) -> list[str]:
    text = " ".join(index.text)
    version_failures: list[str] = []
    try:
        versions = current_versions()
    except RuntimeError as exc:
        versions = None
        version_failures.append(f"index.html: could not read current versions: {exc}")
    if versions is None:
        core = plumed = yoda = crate = pypi = ""
    else:
        core = bare_version(versions["seams-core"])
        plumed = versions["dseams-plumed"]
        yoda = versions["yodaStruct"]
        crate = bare_version(versions["dseams-rs"])
        pypi = versions["pydseamslib"]
    required = (
        "pip install pydseamslib",
        "import pydseams",
        'require("dseams")',
        "seams-core",
        "yodaStruct",
        "dseams-plumed",
        "DSEAMS_CAGES",
        "linkcell",
        "readcon-core",
        "dseams2_repro",
        "dseams-r",
        "Dseams.jl",
        "dseams-rs",
        "dseams-fortran",
        "not on LuaRocks yet",
        "not on CRAN yet",
        "not in the Julia General registry yet",
        "not on conda-forge yet",
        "density-z",
        "chill-plus",
        "fingerprint",
        "topology keys",
        "read, chill, chill-plus, ovito-chill+, cages, symmetry, rings, prisms, cluster, fingerprint, ions, f4, steinhardt, rdf, cn, hbonds, pairs, density-z, and domains",
        "1.x recording",
        "2.x recording",
        "recording was made with seams 2.7.0",
    )
    forbidden = (
        "pip install pydseams ",
        "Needs its own recording",
        "Until that exists",
        "Use the runnable",
        "Software 2.2",
        "three packages",
        "Three packages",
        "libyodaLib",
        "2.9.0",
        "0.1.0",
        "0.3.0",
        "v0.3.1",
        "releases under the seams-core version",
        "Twelve repositories",
        "Eight repositories",
        "repro/reference/",
    )
    failures = list(version_failures)
    failures.extend(
        f"index.html: missing public contract: {value}" for value in required if value not in text
    )
    if versions is not None:
        derived = (
            core,
            versions["seams-core"],
            plumed,
            pypi,
            f"Latest on PyPI is {pypi}",
            f"Latest tag is {yoda}",
            f"crate at {crate}",
        )
        failures.extend(
            f"index.html: missing public contract: {value}"
            for value in derived
            if value not in text
        )
    failures.extend(
        f"index.html: stale or invalid copy: {value}"
        for value in forbidden
        if value in f"{text} "
    )

    hrefs = href_values(index)
    required_hrefs = (
        "https://github.com/d-SEAMS/seams-core",
        "https://github.com/d-SEAMS/PydSEAMSlib",
        "https://github.com/d-SEAMS/yodaStruct",
        "https://github.com/d-SEAMS/linkcell",
        "https://github.com/d-SEAMS/wiki",
        "https://github.com/d-SEAMS/landing",
        "https://github.com/d-SEAMS/dseams-plumed",
        "https://github.com/d-SEAMS/dseams2_repro",
        "https://github.com/d-SEAMS/dseams-r",
        "https://github.com/d-SEAMS/Dseams.jl",
        "https://github.com/d-SEAMS/dseams-rs",
        "https://github.com/d-SEAMS/dseams-fortran",
        "https://github.com/lode-org/readcon-core",
        "https://docs.dseams.info",
        "https://wiki.dseams.info",
        "https://d-seams.github.io/PydSEAMSlib/",
        "https://d-seams.github.io/yodaStruct/",
        "https://cdn.jsdelivr.net/npm/asciinema-player@3.17.0/dist/bundle/asciinema-player.css",
        "casts/dseams-2x.cast",
    )
    failures.extend(
        f"index.html: missing required href: {url}"
        for url in required_hrefs
        if not has_href(hrefs, url)
    )

    srcs = [url for _tag, attribute, url in index.links if attribute == "src"]
    required_srcs = (
        "https://cdn.jsdelivr.net/npm/asciinema-player@3.17.0/dist/bundle/asciinema-player.min.js",
        "https://asciinema.org/a/4KAQce0vldH90WcANWBDACSwD.js",
    )
    failures.extend(
        f"index.html: missing required src: {url}"
        for url in required_srcs
        if url not in srcs
    )

    cast = site / "casts" / "dseams-2x.cast"
    if not cast.is_file():
        failures.append("casts/dseams-2x.cast: missing 2.x recording")
    else:
        cast_text = cast.read_text(encoding="utf-8")
        for value in (
            "seams",
            "2.7.0",
            "pip install pydseamslib",
            "import pydseams",
        ):
            if value not in cast_text:
                failures.append(f"casts/dseams-2x.cast: missing public contract: {value}")
        if (
            'require("dseams")' not in cast_text
            and r'require(\"dseams\")' not in cast_text
        ):
            failures.append(
                'casts/dseams-2x.cast: missing public contract: require("dseams")'
            )

    css = site / "css" / "site.css"
    if not css.is_file():
        failures.append("css/site.css: missing stylesheet")
    elif ":focus-visible" not in css.read_text(encoding="utf-8"):
        failures.append("css/site.css: missing visible keyboard focus style")
    return failures


def check_site(site: Path) -> list[str]:
    site = site.resolve()
    pages = sorted(path.resolve() for path in site.rglob("*.html"))
    if not pages:
        return [f"no HTML pages found under {site}"]

    parsed_pages = {page: parse_page(page) for page in pages}
    index_path = (site / "index.html").resolve()
    if index_path not in parsed_pages:
        return ["index.html: missing landing page"]

    failures: list[str] = []
    for source, page in parsed_pages.items():
        failures.extend(check_page(site, source, page))
    failures.extend(check_links(site, parsed_pages))
    failures.extend(check_contract(site, parsed_pages[index_path]))
    failures.extend(check_internal_text(site))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args()
    failures = check_site(args.site)
    if failures:
        print("\n".join(failures))
        return 1
    print("static site contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
