#!/usr/bin/env python3
"""Dependency-free UDP reachability probe for the flannel VXLAN preflight.

Usage:
  udp_probe.py listen <port> <duration>
      Bind UDP <port> (dual-stack when the kernel allows it) and collect
      datagram payloads for <duration> seconds. Print each unique payload (the
      sending node's name) on its own line, then exit 0.

  udp_probe.py send <port> <token> <host> [<host> ...]
      Send a handful of <token> datagrams to each <host>:<port>, then exit 0.

Only the standard library is used, so it runs anywhere Python 3 (already an
Ansible prerequisite) is present, with no extra packages. UDP is connectionless,
so reachability can only be proven by a cooperative listener confirming receipt
of the actual overlay port traffic — a plain ping would pass even when the
security group blocks the VXLAN port.
"""
import socket
import sys
import time

SEND_COUNT = 5
SEND_INTERVAL = 0.3


def listen(port, duration):
    # Prefer a dual-stack v6 socket so a single listener catches both IPv4
    # (v4-mapped) and IPv6 probes; fall back to plain IPv4 where that is refused.
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        sock.bind(("::", port))
    except OSError:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)
    deadline = time.monotonic() + duration
    received = set()
    while time.monotonic() < deadline:
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        token = data.decode("utf-8", "replace").strip()
        if token:
            received.add(token)
    for token in sorted(received):
        print(token)
    return 0


def send(port, token, hosts):
    payload = token.encode("utf-8")
    for _ in range(SEND_COUNT):
        for host in hosts:
            try:
                info = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM)[0]
            except socket.gaierror:
                continue
            family, socktype, proto, _canon, sockaddr = info
            with socket.socket(family, socktype, proto) as sock:
                sock.sendto(payload, sockaddr)
        time.sleep(SEND_INTERVAL)
    return 0


def main(argv):
    if len(argv) >= 4 and argv[1] == "listen" and len(argv) == 4:
        return listen(int(argv[2]), float(argv[3]))
    if len(argv) >= 5 and argv[1] == "send":
        return send(int(argv[2]), argv[3], argv[4:])
    sys.stderr.write(
        "usage: udp_probe.py listen <port> <duration> | "
        "send <port> <token> <host> [host ...]\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
