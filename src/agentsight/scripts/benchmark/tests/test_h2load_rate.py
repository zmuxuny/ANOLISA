"""Verify HTTP/2 load rate arguments and, when installed, actual wire pacing."""

from __future__ import annotations

import json
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "single_run" / "load" / "h2load.sh"
H2LOAD = shutil.which("h2load")
try:
    import h2.config
    import h2.connection
    import h2.events
except ImportError:
    h2 = None


class H2loadRateTests(unittest.TestCase):
    def capture_arguments(self, **overrides):
        with tempfile.TemporaryDirectory(prefix="h2load rate ") as directory:
            root = Path(directory)
            fake = root / "h2load"
            fake.write_text(
                "#!/usr/bin/env python3\nimport json,os,sys\n"
                "with open(os.environ['ARG_LOG'], 'w') as out: json.dump(sys.argv[1:],out)\n"
                "sys.exit(int(os.environ.get('FAKE_EXIT','0')))\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            output = root / "arguments.json"
            env = dict(
                os.environ,
                PATH=f"{root}:{os.environ['PATH']}",
                ARG_LOG=str(output),
                BASE_URL="https://127.0.0.1:8443",
                PAYLOAD_FILE=str(root / "payload file.json"),
                QPS="200",
                DURATION="2",
            )
            for key in ("CLIENTS", "STREAMS", "THREADS", "FAKE_EXIT"):
                env.pop(key, None)
            env.update(overrides)
            result = subprocess.run(
                ["bash", str(SCRIPT)], env=env, capture_output=True, text=True
            )
            return result, json.loads(output.read_text(encoding="utf-8"))

    def test_default_clients_share_the_requested_rate(self):
        result, arguments = self.capture_arguments()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-n400", arguments)
        self.assertIn("--clients=100", arguments)
        self.assertEqual(
            float(
                next(
                    arg.split("=", 1)[1]
                    for arg in arguments
                    if arg.startswith("--rps=")
                )
            ),
            2,
        )

    def test_custom_clients_receive_fractional_rate(self):
        result, arguments = self.capture_arguments(
            QPS="10", CLIENTS="4", THREADS="2", STREAMS="3"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-n20", arguments)
        self.assertIn("--threads=2", arguments)
        self.assertIn("--max-concurrent-streams=3", arguments)
        self.assertEqual(
            float(
                next(
                    arg.split("=", 1)[1]
                    for arg in arguments
                    if arg.startswith("--rps=")
                )
            ),
            2.5,
        )

    def test_payload_path_and_target_are_preserved(self):
        result, arguments = self.capture_arguments()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(arg.startswith("--data=") for arg in arguments), 1)
        self.assertTrue(
            next(arg for arg in arguments if arg.startswith("--data=")).endswith(
                "payload file.json"
            )
        )
        self.assertEqual(arguments[-1], "https://127.0.0.1:8443/v1/chat/completions")

    def test_load_generator_failure_is_preserved(self):
        result, _ = self.capture_arguments(FAKE_EXIT="23")
        self.assertEqual(result.returncode, 23)

    @unittest.skipUnless(
        H2LOAD and h2, "real wire pacing requires h2load and python-h2"
    )
    def test_real_http2_requests_are_paced_for_single_and_multiple_clients(self):
        for clients, qps in ((1, 5), (2, 5)):
            with self.subTest(clients=clients, qps=qps):
                arrivals = []

                class Handler(socketserver.BaseRequestHandler):
                    def handle(self):
                        self.request.settimeout(5)
                        connection = h2.connection.H2Connection(
                            config=h2.config.H2Configuration(client_side=False)
                        )
                        connection.initiate_connection()
                        self.request.sendall(connection.data_to_send())
                        try:
                            while data := self.request.recv(65536):
                                for event in connection.receive_data(data):
                                    if isinstance(event, h2.events.DataReceived):
                                        connection.acknowledge_received_data(
                                            event.flow_controlled_length,
                                            event.stream_id,
                                        )
                                    if isinstance(event, h2.events.StreamEnded):
                                        arrivals.append(time.monotonic())
                                        connection.send_headers(
                                            event.stream_id,
                                            [
                                                (":status", "200"),
                                                ("content-length", "2"),
                                            ],
                                        )
                                        connection.send_data(
                                            event.stream_id, b"ok", end_stream=True
                                        )
                                self.request.sendall(connection.data_to_send())
                        except (OSError, h2.exceptions.H2Error):
                            pass

                with socketserver.ThreadingTCPServer(
                    ("127.0.0.1", 0), Handler
                ) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        with tempfile.TemporaryDirectory() as directory:
                            payload = Path(directory) / "payload.json"
                            payload.write_text("{}", encoding="utf-8")
                            env = dict(
                                os.environ,
                                BASE_URL=f"http://127.0.0.1:{server.server_address[1]}",
                                QPS=str(qps),
                                DURATION="2",
                                CLIENTS=str(clients),
                                STREAMS="10",
                                THREADS="1",
                                PAYLOAD_FILE=str(payload),
                            )
                            result = subprocess.run(
                                ["bash", str(SCRIPT)],
                                env=env,
                                capture_output=True,
                                text=True,
                                timeout=8,
                            )
                    finally:
                        server.shutdown()
                        thread.join()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(arrivals), qps * 2, result.stdout)
                span = max(arrivals) - min(arrivals)
                self.assertGreaterEqual(
                    span,
                    1.3,
                    f"{len(arrivals)} requests arrived as an unpaced burst spanning {span:.3f}s",
                )
                print(
                    f"real h2load clients={clients} requests={len(arrivals)} arrival_span={span:.3f}s",
                    flush=True,
                )


if __name__ == "__main__":
    unittest.main()
