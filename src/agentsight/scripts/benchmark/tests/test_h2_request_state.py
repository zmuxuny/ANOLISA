"""Exercise HTTP/2 request identity and cancellation over real protocol frames."""

import gc
import importlib.util
import json
import socket
import tempfile
import threading
import unittest
import weakref
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import DataReceived, PingAckReceived, StreamEnded
except ImportError:
    H2Connection = None

SCRIPT = Path(__file__).parents[1] / "single_run" / "mock_llm_server.py"
spec = importlib.util.spec_from_file_location("h2_state_server", SCRIPT)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class WireClient:
    def __init__(self, connection):
        self.socket = connection
        self.h2 = H2Connection(config=H2Configuration(client_side=True))
        self.h2.initiate_connection()
        self.flush()
        self.events = []
        self.bodies = {}

    def flush(self):
        data = self.h2.data_to_send()
        if data:
            self.socket.sendall(data)

    def until(self, predicate):
        while not predicate():
            data = self.socket.recv(65535)
            if not data:
                raise AssertionError("server closed before the expected HTTP/2 event")
            for event in self.h2.receive_data(data):
                self.events.append(event)
                if isinstance(event, DataReceived):
                    self.bodies.setdefault(event.stream_id, bytearray()).extend(
                        event.data
                    )
                    self.h2.acknowledge_received_data(
                        event.flow_controlled_length, event.stream_id
                    )
            self.flush()

    def request(self, stream_id, body=b"{}", request_id=None, end=True):
        headers = [
            (":method", "POST"),
            (":scheme", "https"),
            (":authority", "localhost"),
            (":path", "/v1/chat/completions"),
            ("x-benchmark-run-id", "fixture"),
        ]
        if request_id is not None:
            headers.append(("x-request-id", request_id))
        self.h2.send_headers(stream_id, headers)
        self.h2.send_data(stream_id, body, end_stream=end)
        self.flush()

    def response(self, stream_id):
        self.until(
            lambda: any(
                isinstance(e, StreamEnded) and e.stream_id == stream_id
                for e in self.events
            )
        )
        return json.loads(self.bodies[stream_id])

    def barrier(self, token):
        self.h2.ping(token)
        self.flush()
        self.until(
            lambda: any(
                isinstance(e, PingAckReceived) and e.ping_data == token
                for e in self.events
            )
        )


@contextmanager
def connection(recorder=None):
    client, peer = socket.socketpair()
    client.settimeout(3)
    peer.settimeout(3)
    settings = SimpleNamespace(
        chunks=1, chunk_bytes=8, chunk_delay=0, sse=False, request_recorder=recorder
    )
    errors = []

    def serve():
        try:
            server.serve_h2(peer, settings, False)
        except Exception as error:  # noqa: BLE001
            # Propagate worker failures to the test thread.
            errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield WireClient(client)
    finally:
        client.close()
        thread.join(timeout=4)
        peer.close()
        if thread.is_alive():
            raise AssertionError("HTTP/2 fixture failed to stop")
        if errors:
            raise AssertionError(f"HTTP/2 server failed: {errors!r}")


@unittest.skipIf(
    H2Connection is None, "optional benchmark h2 dependency is unavailable"
)
class H2RequestStateTests(unittest.TestCase):
    def test_header_id_is_preserved_in_response_and_actual_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = server.RequestRecorder(Path(directory))
            try:
                with connection(recorder) as client:
                    client.request(1, request_id="header-fixture")
                    self.assertEqual(client.response(1)["request_id"], "header-fixture")
                rows = [
                    json.loads(line)
                    for line in (Path(directory) / "fixture.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                self.assertEqual(
                    rows, [{"request_id": "header-fixture", "http_status": 200}]
                )
            finally:
                recorder.close()

    def test_body_id_still_has_precedence_over_header(self):
        with connection() as client:
            client.request(1, b'{"request_id":"body-fixture"}', "header-fixture")
            self.assertEqual(client.response(1)["request_id"], "body-fixture")

    def test_missing_id_keeps_the_existing_fallback(self):
        with connection() as client:
            client.request(1)
            self.assertEqual(client.response(1)["request_id"], "bench-missing")

    def test_interleaved_streams_keep_their_own_headers(self):
        with connection() as client:
            client.request(1, b"{", "first", end=False)
            client.request(3, b"{}", "second")
            self.assertEqual(client.response(3)["request_id"], "second")
            client.h2.send_data(1, b"}", end_stream=True)
            client.flush()
            self.assertEqual(client.response(1)["request_id"], "first")

    def test_cancelled_stream_releases_its_body_and_keeps_other_stream(self):
        references = []

        class TrackedBody(bytearray):
            def __init__(self, *args):
                super().__init__(*args)
                references.append(weakref.ref(self))

        with (
            mock.patch.object(server, "bytearray", TrackedBody, create=True),
            connection() as client,
        ):
            client.request(1, b"cancel me", "cancelled", end=False)
            client.request(3, b"{", "retained", end=False)
            client.barrier(b"ready123")
            gc.collect()
            self.assertEqual(sum(ref() is not None for ref in references), 2)
            client.h2.reset_stream(1)
            client.barrier(b"reset123")
            gc.collect()
            self.assertEqual(sum(ref() is not None for ref in references), 1)
            client.h2.send_data(3, b"}", end_stream=True)
            client.flush()
            self.assertEqual(client.response(3)["request_id"], "retained")
            client.barrier(b"ended123")
            gc.collect()
            self.assertEqual(sum(ref() is not None for ref in references), 0)


if __name__ == "__main__":
    unittest.main()
