"""Tests for exceptions in the static site contract."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check-site.py")
SPEC = importlib.util.spec_from_file_location("check_site", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK_SITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_SITE)


class ForthcomingNoticeTests(unittest.TestCase):
    def test_allows_exact_paper_notice(self) -> None:
        source = '<p id="forthcoming-paper-status">Coming soon.</p>'

        self.assertEqual(CHECK_SITE.check_forthcoming_notice(source), [])

    def test_rejects_release_status_notice(self) -> None:
        source = (
            '<p id="forthcoming-paper-status">Coming soon.</p>'
            '<p class="release-status">Package coming soon.</p>'
        )

        self.assertEqual(
            CHECK_SITE.check_forthcoming_notice(source),
            ["index.html: reader-facing plumbing: coming soon"],
        )


if __name__ == "__main__":
    unittest.main()
