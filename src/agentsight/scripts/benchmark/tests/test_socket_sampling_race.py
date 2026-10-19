"""A closing descriptor must not erase other live sockets from a sample."""

import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "single_run"))
import collect_metrics


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs collector")
class SocketSamplingTests(unittest.TestCase):
    def setUp(self):
        self.sockets = [*socket.socketpair(), *socket.socketpair()]
        for sock in self.sockets:
            self.addCleanup(sock.close)
        self.paths = [Path(f"/proc/{os.getpid()}/fd/{sock.fileno()}") for sock in self.sockets]
        self.directory = Path(f"/proc/{os.getpid()}/fd")
        real_iterdir = Path.iterdir
        self.patch = mock.patch.object(
            Path, "iterdir", lambda path: iter(self.paths) if path == self.directory else real_iterdir(path)
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_close_between_symlink_check_and_readlink_keeps_other_sockets(self):
        real_readlink = os.readlink
        closing = self.paths[1]

        def readlink(path, *args, **kwargs):
            if path == closing:
                self.sockets[1].close()
            return real_readlink(path, *args, **kwargs)

        with mock.patch.object(collect_metrics.os, "readlink", side_effect=readlink):
            self.assertEqual(collect_metrics.socket_count(os.getpid()), 3)
        self.assertFalse(closing.is_symlink())

    def test_one_inaccessible_descriptor_does_not_discard_the_sample(self):
        real_readlink = os.readlink

        def readlink(path, *args, **kwargs):
            if path == self.paths[2]:
                raise PermissionError("descriptor changed during observation")
            return real_readlink(path, *args, **kwargs)

        with mock.patch.object(collect_metrics.os, "readlink", side_effect=readlink):
            self.assertEqual(collect_metrics.socket_count(os.getpid()), 3)

    def test_already_closed_descriptors_and_regular_files_are_not_sockets(self):
        self.sockets[0].close()
        with tempfile.TemporaryFile() as regular:
            self.paths.append(Path(f"/proc/{os.getpid()}/fd/{regular.fileno()}"))
            # The closed fd may be reused by the temporary file. Neither entry
            # for that regular file is counted, while the other sockets remain.
            self.assertEqual(collect_metrics.socket_count(os.getpid()), 3)

    def test_all_closed_and_process_disappearance_return_zero(self):
        for sock in self.sockets:
            sock.close()
        self.assertEqual(collect_metrics.socket_count(os.getpid()), 0)
        with mock.patch.object(Path, "iterdir", side_effect=FileNotFoundError("process exited")):
            self.assertEqual(collect_metrics.socket_count(os.getpid()), 0)

    def test_stable_socket_count_is_unchanged(self):
        self.assertEqual(collect_metrics.socket_count(os.getpid()), 4)


if __name__ == "__main__":
    unittest.main()
