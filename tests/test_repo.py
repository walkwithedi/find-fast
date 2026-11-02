"""Repository-level tests: version file and changelog."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RepoTest(unittest.TestCase):
    def test_version_has_changelog_section(self):
        version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        log = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        self.assertRegex(log, r"(?m)^## %s$" % re.escape(version))


if __name__ == "__main__":
    unittest.main()
