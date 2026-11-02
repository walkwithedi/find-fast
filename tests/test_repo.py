"""Repository-level tests: version file and changelog."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RepoTest(unittest.TestCase):
    def test_version_has_changelog_section(self):
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            log = f.read()
        self.assertRegex(log, r"(?m)^## %s$" % re.escape(version))


if __name__ == "__main__":
    unittest.main()


def exec_args(value):
    """Arguments of a desktop entry Exec value: string escapes first, then quoting, where
    a backslash inside double quotes escapes ", `, $ and itself (Desktop Entry Specification)."""
    value = value.replace("\\\\", "\\")
    args, cur, quoted, i, started = [], "", False, 0, False
    while i < len(value):
        ch = value[i]
        if quoted:
            if ch == "\\" and i + 1 < len(value) and value[i + 1] in '"`$\\':
                cur += value[i + 1]
                i += 1
            elif ch == '"':
                quoted = False
            else:
                cur += ch
        elif ch == '"':
            quoted = started = True
        elif ch == " ":
            if started:
                args.append(cur)
            cur, started = "", False
        else:
            cur += ch
            started = True
        i += 1
    if started:
        args.append(cur)
    return args


class DesktopEntryTest(unittest.TestCase):
    def test_launcher_runs_the_program_next_to_the_real_file(self):
        import configparser
        import subprocess
        import tempfile
        path = os.path.join(ROOT, "双击运行.desktop")
        c = configparser.RawConfigParser()
        c.optionxform = str
        c.read(path, encoding="utf-8")
        entry = c["Desktop Entry"]
        self.assertEqual(entry["Name"], "秒搜文件")
        self.assertEqual(entry["Terminal"], "false")
        self.assertTrue(os.access(path, os.X_OK))
        args = exec_args(entry["Exec"])
        with tempfile.TemporaryDirectory() as d:
            link = os.path.join(d, "link.desktop")
            os.symlink(path, link)
            fake = os.path.join(d, "bin")
            os.mkdir(fake)
            with open(os.path.join(fake, "python3"), "w") as f:
                f.write('#!/bin/sh\necho "$@"\n')
            os.chmod(os.path.join(fake, "python3"), 0o755)
            env = dict(os.environ, PATH=fake + os.pathsep + os.environ["PATH"])
            out = subprocess.run([a if a != "%k" else link for a in args], capture_output=True, text=True,
                                 env=env, timeout=30).stdout.strip()
        self.assertEqual(out, os.path.join(ROOT, "find_fast.py"))
