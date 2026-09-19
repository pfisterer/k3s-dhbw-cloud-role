#!/usr/bin/env python3
"""Dependency-free UDP reachability probe for the flannel VXLAN preflight.

Usage:
  udp_probe.py listen <port> <duration> <ready-file> <expected> [<expected> ...]
      Bind UDP <port> (dual-stack when the kernel allows it) and collect
      datagram payloads for at most <duration> seconds. Create <ready-file> once
      the socket is bound, and exit early after every expected sender token has
      arrived. Print each unique payload on its own line, then exit 0.

  udp_probe.py send <port> <token> <host> [<host> ...]
      Send a handful of <token> datagrams to each <host>:<port>. A host that
      cannot be written to is reported on stderr and does not stop the
      remaining hosts. Exit 0 only when every host was written to at least
      once, exit 1 otherwise.

Only the standard library is used, so it runs anywhere Python 3 (already an
Ansible prerequisite) is present, with no extra packages. UDP is connectionless,
so reachability can only be proven by a cooperative listener confirming receipt
of the actual overlay port traffic — a plain ping would pass even when the
security group blocks the VXLAN port.
"""
import os
import socket
import sys
import time

SEND_COUNT = 5
SEND_INTERVAL = 0.3


def listen(port, duration, ready_file, expected_tokens):
    # Prefer a dual-stack v6 socket so a single listener catches both IPv4
    # (v4-mapped) and IPv6 probes; fall back to plain IPv4 where that is refused.
    sock = None
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        sock.bind(("::", port))
    except OSError:
        if sock is not None:
            sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", port))
    try:
        sock.settimeout(0.5)
        with open(ready_file, "w", encoding="utf-8") as marker:
            marker.write("ready\n")

        expected = set(expected_tokens)
        deadline = time.monotonic() + duration
        received = set()
        while (
            time.monotonic() < deadline
            and not expected.issubset(received)
            and os.path.exists(ready_file)
        ):
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            token = data.decode("utf-8", "replace").strip()
            if token:
                received.add(token)
    finally:
        sock.close()
    for token in sorted(received):
        print(token)
    return 0


def send(port, token, hosts):
    # A destination is usually given as one address per family, and k3s later
    # hands all of them to flannel. An address that fails locally, because no
    # route exists or a local rule rejects it or it does not resolve, must not
    # skip the remaining addresses, otherwise a reachable family stays untried
    # and the caller reads the missing token as a blocked port. It must also not
    # be forgiven either. The caller passes the addresses it will hand to k3s as
    # --node-ip, and neither it nor this script can know which of them the CNI
    # will end up using as a tunnel endpoint. Letting one working address vouch
    # for the rest would pass a node whose other address is locally unreachable,
    # so every address is tried and every one has to succeed at least once. That
    # is deliberately conservative and will fail a node whose second address the
    # CNI never uses.
    # socket.gaierror is an OSError subclass, so one handler covers both the
    # lookup and the write.
    payload = token.encode("utf-8")
    delivered = set()
    failures = {}
    for _ in range(SEND_COUNT):
        for host in hosts:
            try:
                info = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM)[0]
                family, socktype, proto, _canon, sockaddr = info
                with socket.socket(family, socktype, proto) as sock:
                    sock.sendto(payload, sockaddr)
            except OSError as error:
                failures.setdefault(host, []).append(error)
                continue
            delivered.add(host)
        time.sleep(SEND_INTERVAL)
    for host, errors in sorted(failures.items()):
        seen = []
        for error in errors:
            if str(error) not in seen:
                seen.append(str(error))
        sys.stderr.write(
            "send to %s failed %d of %d times with %s\n"
            % (host, len(errors), SEND_COUNT, " and ".join(seen))
        )
    unwritten = [host for host in hosts if host not in delivered]
    if unwritten:
        sys.stderr.write(
            "no datagram left this node for %s\n" % ", ".join(unwritten)
        )
        return 1
    return 0


def main(argv):
    if len(argv) >= 6 and argv[1] == "listen":
        return listen(int(argv[2]), float(argv[3]), argv[4], argv[5:])
    if len(argv) >= 5 and argv[1] == "send":
        return send(int(argv[2]), argv[3], argv[4:])
    sys.stderr.write(
        "usage: udp_probe.py listen <port> <duration> <ready-file> "
        "<expected> [expected ...] | "
        "send <port> <token> <host> [host ...]\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
