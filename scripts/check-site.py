"""Validate the static landing page without network access."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
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
        self.meta: list[dict[str, str]] = []
        self.link_tags: list[dict[str, str]] = []
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
        if tag == "meta":
            self.meta.append({key: value or "" for key, value in attrs})
        elif tag == "link":
            self.link_tags.append({key: value or "" for key, value in attrs})

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
    (r"\belja\b", "cluster host name"),
    (r"\bjobs?\s*#?\d{3,}", "job id"),
    (r"\bbase\b[^.\n]{0,60}\bvs\b[^.\n]{0,60}\btip\b", "revision comparison"),
    (r"\bpaper_manifest\b", "manifest file name"),
    (r"results/reference", "internal results path"),
    (r"(?<![\w./-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])", "commit hash or job number"),
    (r"\bexclusive\b", "scheduler wording"),
    (r"\bmanifest:\b", "manifest label"),
)


def check_internal_text(site: Path) -> list[str]:
    failures: list[str] = []
    for name in ("index.html", "README.md"):
        p = site / name
        if not p.is_file():
            continue
        for number, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in INTERNAL_TEXT:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    failures.append(
                        f"{name}:{number}: internal text ({label}): {match.group(0)}"
                    )
                    break
    return failures


def check_contract(site: Path, index: PageParser) -> list[str]:
    text = " ".join(index.text)
    required = (
        "pip install pydseamslib",
        "cargo add dseams",
        "pip install linkcell",
        "CHILL+",
        "clathrate",
        "pixi run build",
        "remotes::install_github",
        "meson setup bbdir --wrap-mode=nofallback",
        "dseams-fortran",
        "dseams-plumed",
    )
    reader_forbidden = (
        "live index",
        "checked against",
        "conda-forge yet",
        "not on conda-forge",
        "install.json",
        "check-registries",
        "published</td>",
        ">published<",
        ">source<",
        "Status</th>",
        "coming soon",
    )
    forbidden = (
        "Elja",
        "job 1785712",
        "asciinema",
        "repro/reference",
        "libyodaLib",
        "2.7.0",
        "Antics",
        "fonts.googleapis",
        "gstatic.com",
    )
    html_raw = (site / "index.html").read_text(encoding="utf-8")
    failures = [f"index.html: missing public contract: {value}" for value in required if value not in text]
    failures.extend(
        f"index.html: stale or invalid copy: {value}"
        for value in forbidden
        if value in f"{text} "
    )
    failures.extend(
        f"index.html: reader-facing plumbing: {value}"
        for value in reader_forbidden
        if value in html_raw
    )
    for needle in ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net", "cdn.jsdelivr.net/npm/@fontsource"):
        if needle in html_raw:
            failures.append(f"index.html: external font or player CDN: {needle}")
    if 'loading="lazy"' in html_raw:
        failures.append("index.html: do not lazy-load images; all figures must load eagerly")

    hrefs = href_values(index)
    books = (
        "https://docs.dseams.info",
        "https://python.dseams.info",
        "https://rust.dseams.info",
        "https://julia.dseams.info",
        "https://fortran.dseams.info",
        "https://lua.dseams.info",
        "https://r.dseams.info",
        "https://plumed.dseams.info",
        "https://linkcell.dseams.info",
    )
    failures.extend(
        f"index.html: missing required href: {url}"
        for url in books
        if not has_href(hrefs, url)
    )

    if not has_href(hrefs, "https://github.com/d-SEAMS"):
        failures.append("index.html: missing GitHub org link")

    logo = site / "images" / "logo" / "dSeamsLogo.png"
    if not logo.is_file():
        failures.append("images/logo/dSeamsLogo.png: missing logo asset")
    elif "images/logo/dSeamsLogo.png" not in [u for _t, a, u in index.links if a == "src"]:
        failures.append("index.html: logo must appear in img src")

    manifest = site / "install.json"
    if not manifest.is_file():
        failures.append("install.json: missing install manifest")
    else:
        entries = json.loads(manifest.read_text(encoding="utf-8")).get("packages", [])
        for entry in entries:
            page_cmd = entry.get("page_command", entry.get("command", ""))
            if page_cmd:
                snippet = page_cmd if len(page_cmd) < 48 else page_cmd.split()[0]
                if page_cmd not in html_raw and snippet not in html_raw:
                    failures.append(f"install.json: page command missing on page: {page_cmd}")
            book = (entry.get("book") or "").rstrip("/")
            if book and not has_href(hrefs, book):
                failures.append(f"install.json: missing book href: {book}")

    for fig in (
        "images/dSEAMS/image7.png",
        "images/science/gallery-cages-sII.png",
        "images/science/gallery-rings.png",
        "images/science/gallery-interface.png",
        "images/science/gallery-interface-raw.png",
        "images/science/sii.png",
    ):
        if not (site / fig).is_file():
            failures.append(f"{fig}: missing science still")

    js_file = site / "js" / "site.js"
    if not js_file.is_file():
        failures.append("js/site.js: missing interactive script")
    elif js_file.stat().st_size >= 30_720:
        failures.append("js/site.js: exceeds 30 KB budget")

    css = site / "css" / "site.css"
    if not css.is_file():
        failures.append("css/site.css: missing stylesheet")
    else:
        css_text = css.read_text(encoding="utf-8")
        if ":focus-visible" not in css_text:
            failures.append("css/site.css: missing visible keyboard focus style")
        for bad in (".lattice", "Source Serif", "Source Sans", "fonts.googleapis"):
            if bad in css_text:
                failures.append(f"css/site.css: generic template marker: {bad}")
    return failures


def check_seo(site: Path, index: PageParser) -> list[str]:
    failures: list[str] = []
    descriptions = [
        item.get("content", "")
        for item in index.meta
        if item.get("name", "").lower() == "description"
    ]
    if len(descriptions) != 1 or not descriptions[0]:
        failures.append("index.html: expected one non-empty meta description")

    canonicals = [
        item.get("href", "")
        for item in index.link_tags
        if "canonical" in item.get("rel", "").lower().split()
    ]
    if canonicals != ["https://dseams.info/"]:
        failures.append("index.html: canonical must be https://dseams.info/")

    required_properties = {
        "og:site_name": "d-SEAMS",
        "og:title": "",
        "og:description": "",
        "og:type": "website",
        "og:url": "https://dseams.info/",
        "og:image": "https://dseams.info/images/og-card.png",
        "og:image:alt": "",
    }
    for prop, expected in required_properties.items():
        values = [
            item.get("content", "")
            for item in index.meta
            if item.get("property", "").lower() == prop
        ]
        if len(values) != 1 or not values[0] or (expected and values[0] != expected):
            failures.append(f"index.html: invalid {prop}")

    required_names = {
        "twitter:card": "summary_large_image",
        "twitter:title": "",
        "twitter:description": "",
        "twitter:image": "https://dseams.info/images/og-card.png",
        "twitter:image:alt": "",
    }
    for name, expected in required_names.items():
        values = [
            item.get("content", "")
            for item in index.meta
            if item.get("name", "").lower() == name
        ]
        if len(values) != 1 or not values[0] or (expected and values[0] != expected):
            failures.append(f"index.html: invalid {name}")

    image = site / "images" / "og-card.png"
    if not image.is_file():
        failures.append("images/og-card.png: missing social image")

    robots = site / "robots.txt"
    if not robots.is_file():
        failures.append("robots.txt: missing")
    else:
        text = robots.read_text(encoding="utf-8")
        if "User-agent: *" not in text or "Allow: /" not in text:
            failures.append("robots.txt: crawlers must be allowed")
        if "Sitemap: https://dseams.info/sitemap.xml" not in text:
            failures.append("robots.txt: missing sitemap URL")

    sitemap = site / "sitemap.xml"
    if not sitemap.is_file():
        failures.append("sitemap.xml: missing")
    else:
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locations = [
            item.text or ""
            for item in ET.parse(sitemap).findall(".//sm:loc", namespace)
        ]
        if locations != ["https://dseams.info/"]:
            failures.append("sitemap.xml: expected only https://dseams.info/")

    source = (site / "index.html").read_text(encoding="utf-8")
    blocks = re.findall(
        r'<script\s+type="application/ld\+json"\s*>(.*?)</script>',
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(blocks) != 1:
        failures.append("index.html: expected one JSON-LD graph")
    else:
        graph = json.loads(blocks[0]).get("@graph", [])
        types = {node.get("@type") for node in graph if isinstance(node, dict)}
        required_types = {"SoftwareApplication", "SoftwareSourceCode", "ScholarlyArticle"}
        if not required_types.issubset(types):
            failures.append("index.html: incomplete JSON-LD graph")
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
    hero_src = [url for tag, attribute, url in parsed_pages[index_path].links if tag == "img" and attribute == "src"]
    for need in (
        "images/dSEAMS/image7.png",
        "images/science/gallery-cages-sII.png",
        "images/science/gallery-rings.png",
        "images/science/gallery-interface.png",
        "images/science/gallery-interface-raw.png",
        "images/science/sii.png",
        "images/logo/dSeamsLogo.png",
    ):
        if need not in hero_src:
            failures.append(f"index.html: missing figure or logo src: {need}")
    failures.extend(check_contract(site, parsed_pages[index_path]))
    failures.extend(check_seo(site, parsed_pages[index_path]))
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
