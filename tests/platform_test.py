#!/usr/bin/env python3
"""Synthetic platform facts and safety rules, independent of host ownership."""
import os
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fixtures import init_env, chat_readline_unavailable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# All spark paths are captured at import. Keep them inside this fixture.
HOME = tempfile.TemporaryDirectory(prefix="spark-platform-")
ROOT = os.path.realpath(HOME.name)
os.environ.update(HOME=ROOT, XDG_CONFIG_HOME=ROOT + "/config",
                  XDG_STATE_HOME=ROOT + "/state", XDG_DATA_HOME=ROOT + "/data")
sys.path.insert(0, os.path.join(REPO, "lib"))
import spark
from spark import mcp, uninstall


class PlatformTests(unittest.TestCase):
    def test_init_overrides(self):
        for host in ("linux", "darwin"):
            with self.subTest(host=host), patch("fixtures.sys.platform", host):
                default = init_env(ROOT)
                self.assertEqual("SPARK_ETC_RUNIT" in default, host == "linux")
                for os_name in ("Linux", "Darwin"):
                    for marker in ("installed", "absent"):
                        for live in (True, False):
                            env = init_env(ROOT, SPARK_OS=os_name,
                                           SPARK_ETC_RUNIT=marker, SPARK_VAR_SERVICE="service")
                            self.assertEqual(env["SPARK_ETC_RUNIT"], marker)
                            with patch.dict(os.environ, env), patch.object(spark, "IS_MAC", os_name == "Darwin"), \
                                 patch.object(spark, "RUNIT_DIR", marker), patch.object(spark, "VAR_SERVICE", "service"), \
                                 patch("os.path.isdir", side_effect=lambda p: p == "installed" or (p == "service" and live)):
                                self.assertEqual(spark.init_shape(), "runit" if marker == "installed" else "systemd")
                                self.assertEqual(spark.runit_live(), live)
        with patch.dict(os.environ, {}, clear=True), patch.object(spark, "IS_MAC", True):
            self.assertEqual(spark.init_shape(), "launchd")

    def test_repository_markers(self):
        root = os.path.join(ROOT, "membership")
        os.makedirs(root)
        target = os.path.join(root, "profile")
        link = os.path.join(root, "rc")
        content = b"# mine\n\n. ~/.config/spark/hook.bash\n"
        os.symlink(target, link)
        real_exists = os.path.lexists
        # Model the ancestor tree, not git's willingness to open it. Even
        # an unrelated or malformed marker must retain the conservative refusal.
        for marker in (None, root, os.path.dirname(root), os.path.sep):
            with self.subTest(marker=marker):
                with open(target, "wb") as f:
                    f.write(content)
                def exists(p):
                    if os.path.basename(p) == ".git":
                        return marker is not None and os.path.dirname(p) == marker
                    return real_exists(p)
                with patch("os.path.lexists", side_effect=exists):
                    self.assertEqual(uninstall.rc_tracked(link), target if marker else "")
                    uninstall.strip_rc_line(link)
                with open(target, "rb") as f:
                    self.assertEqual(f.read(), content if marker else b"# mine\n")
                self.assertTrue(os.path.islink(link))
        # Both ordinary .git directories and linked-worktree .git files
        # are real markers. No git subprocess or ownership exception.
        for directory in (True, False):
            marker = os.path.join(root, ".git")
            if directory:
                os.mkdir(marker)
            else:
                with open(marker, "w") as f:
                    f.write("gitdir: ../elsewhere\n")
            with open(target, "wb") as f:
                f.write(content)
            self.assertEqual(uninstall.rc_tracked(link), target)
            uninstall.strip_rc_line(link)
            with open(target, "rb") as f:
                self.assertEqual(f.read(), content)
            os.rmdir(marker) if directory else os.unlink(marker)

    def test_program_ownership(self):
        uid = 1234
        safe = SimpleNamespace(st_uid=uid, st_gid=uid, st_mode=stat.S_IFDIR | 0o755)
        file = SimpleNamespace(st_uid=uid, st_gid=uid, st_mode=stat.S_IFREG | 0o755)
        for owner, mode, private, allowed in ((uid, 0o755, False, True), (0, 0o755, False, True),
                (4321, 0o755, False, False), (uid, 0o777, True, False),
                (uid, 0o775, False, False), (uid, 0o775, True, True),
                (0, 0o1777, False, True), (4321, 0o1777, True, False)):
            with self.subTest(owner=owner, mode=oct(mode), private=private):
                ancestor = SimpleNamespace(st_uid=owner, st_gid=uid, st_mode=stat.S_IFDIR | mode)
                def info(p):
                    return file if p == "/fixture/bin/tool" else ancestor if p == "/fixture" else safe
                with patch("os.getuid", return_value=uid), patch("os.stat", side_effect=info), \
                     patch("os.path.realpath", return_value="/fixture/bin/tool"), patch("os.access", return_value=True), \
                     patch.object(mcp, "private_group", return_value=private):
                    self.assertEqual(mcp.program_problem("/alias/tool") == "", allowed)

    def test_terminal_prerequisites(self):
        self.assertTrue(chat_readline_unavailable("linux", "libedit"))
        self.assertTrue(chat_readline_unavailable("darwin", "no readline"))
        self.assertEqual(chat_readline_unavailable("linux", "GNU readline"), "")
        self.assertEqual(chat_readline_unavailable("darwin", "libedit"), "")


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        HOME.cleanup()
