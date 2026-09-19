import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROBE = Path(__file__).resolve().parents[1] / "files" / "udp_probe.py"


def unused_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class UdpProbeListenerTest(unittest.TestCase):
    def start_listener(self, duration, expected_tokens):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        ready_path = Path(temporary_directory.name) / "listener.ready"
        port = unused_udp_port()
        process = subprocess.Popen(
            [
                sys.executable,
                str(PROBE),
                "listen",
                str(port),
                str(duration),
                str(ready_path),
                *expected_tokens,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.stop_process, process)
        return process, port, ready_path

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.kill()
            process.wait()

    def wait_for_path(self, path, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.01)
        self.fail(f"listener did not create readiness marker {path}")

    def wait_for_process(self, process, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.01)
        self.fail("listener did not stop after readiness marker removal")

    @staticmethod
    def send_token(port, token):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(token.encode("utf-8"), ("127.0.0.1", port))

    def test_listener_creates_ready_marker_after_binding(self):
        process, port, ready_path = self.start_listener(5, ["peer-a"])

        self.wait_for_path(ready_path)

        self.assertIsNone(process.poll())
        self.send_token(port, "peer-a")
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), ["peer-a"])

    def test_listener_waits_for_all_expected_tokens_and_then_exits_early(self):
        duration = 5
        process, port, ready_path = self.start_listener(
            duration, ["peer-a", "peer-b"]
        )
        self.wait_for_path(ready_path)
        started = time.monotonic()

        self.send_token(port, "peer-a")
        time.sleep(0.2)
        self.assertIsNone(process.poll(), "listener exited before every peer arrived")

        self.send_token(port, "peer-b")
        stdout, stderr = process.communicate(timeout=2)

        self.assertLess(time.monotonic() - started, duration)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), ["peer-a", "peer-b"])

    def test_listener_exits_when_readiness_marker_is_removed(self):
        process, _port, ready_path = self.start_listener(5, ["peer-a"])
        self.wait_for_path(ready_path)

        ready_path.unlink()
        self.wait_for_process(process)
        stdout, stderr = process.communicate()

        self.assertEqual(stderr, "")
        self.assertEqual(stdout, "")


class UdpProbeSenderTest(unittest.TestCase):
    # A link-local address without a scope id cannot be routed, so the write
    # fails inside the kernel without any packet reaching a real host.
    UNREACHABLE = "fe80::1"

    def run_send(self, port, token, hosts):
        return subprocess.run(
            [sys.executable, str(PROBE), "send", str(port), token, *hosts],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def bound_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(5)
        self.addCleanup(sock.close)
        return sock, sock.getsockname()[1]

    def test_unresolvable_host_is_reported_and_fails(self):
        result = self.run_send(48473, "peer-a", ["host.invalid.example"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("host.invalid.example", result.stderr)

    def test_failing_address_does_not_skip_the_next_one(self):
        sock, port = self.bound_socket()

        result = self.run_send(port, "peer-a", [self.UNREACHABLE, "127.0.0.1"])

        data, _address = sock.recvfrom(65535)
        self.assertEqual(data.decode("utf-8"), "peer-a")
        self.assertIn(self.UNREACHABLE, result.stderr)

    def test_one_failing_address_is_not_forgiven_by_a_working_one(self):
        sock, port = self.bound_socket()

        result = self.run_send(port, "peer-a", [self.UNREACHABLE, "127.0.0.1"])

        sock.recvfrom(65535)
        self.assertEqual(result.returncode, 1)
        self.assertIn(self.UNREACHABLE, result.stderr)
        self.assertNotIn("127.0.0.1", result.stderr)

    def test_every_address_failing_exits_non_zero(self):
        result = self.run_send(48473, "peer-a", [self.UNREACHABLE])

        self.assertEqual(result.returncode, 1)
        self.assertIn("no datagram left this node", result.stderr)

    def test_reachable_address_alone_stays_silent(self):
        sock, port = self.bound_socket()

        result = self.run_send(port, "peer-a", ["127.0.0.1"])

        data, _address = sock.recvfrom(65535)
        self.assertEqual(data.decode("utf-8"), "peer-a")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
