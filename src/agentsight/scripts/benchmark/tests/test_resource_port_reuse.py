"""A sequential run may reuse the mock server's TIME_WAIT port, never a listener."""

import errno
from pathlib import Path
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "single_run"))
import resource_run


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux resource benchmark")
class ResourcePortTests(unittest.TestCase):
    def listener(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)
        return listener

    def test_completed_server_connection_does_not_block_the_next_run(self):
        server = self.listener()
        address = server.getsockname()
        with socket.create_connection(address, timeout=2) as client:
            connection, _ = server.accept()
            # The server actively closes, putting its local port in TIME_WAIT.
            connection.close()
            self.assertEqual(client.recv(1), b"")
        server.close()
        resource_run.check_port_available(address[1])
        # The probe releases its descriptor; the same reusable listener can bind.
        with socket.socket() as next_server:
            next_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            next_server.bind(address)
            next_server.listen()

    def test_active_listener_is_still_rejected(self):
        server = self.listener()
        with self.assertRaises(OSError) as caught:
            resource_run.check_port_available(server.getsockname()[1])
        self.assertEqual(caught.exception.errno, errno.EADDRINUSE)

    def test_unused_port_probe_does_not_keep_it_bound(self):
        server = self.listener()
        address = server.getsockname()
        server.close()
        resource_run.check_port_available(address[1])
        with socket.socket() as later:
            later.bind(address)
            later.listen()


if __name__ == "__main__":
    unittest.main()
