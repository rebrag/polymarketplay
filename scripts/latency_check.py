from __future__ import annotations

import argparse
import socket
import time
import urllib.request
from typing import Tuple


def measure_dns(host: str) -> Tuple[float, list[tuple]]:
    start = time.perf_counter()
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, infos


def measure_tcp(host: str, ip: str) -> float:
    start = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.5)
    try:
        sock.connect((ip, 443))
    finally:
        sock.close()
    return (time.perf_counter() - start) * 1000


def measure_http(url: str) -> float:
    start = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=4) as resp:
        resp.read(1)
        _ = resp.status
    return (time.perf_counter() - start) * 1000


def pick_ipv4(infos: list[tuple]) -> str | None:
    for family, _, _, _, sockaddr in infos:
        if family == socket.AF_INET:
            return sockaddr[0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="clob.polymarket.com")
    parser.add_argument("--url", default="https://clob.polymarket.com/health")
    args = parser.parse_args()

    host = args.host
    url = args.url

    dns_ms, infos = measure_dns(host)
    ip = pick_ipv4(infos)
    print(f"DNS lookup: {dns_ms:.1f} ms")
    if not ip:
        print("No IPv4 address found.")
        return
    print(f"Resolved IP: {ip}")

    try:
        tcp_ms = measure_tcp(host, ip)
        print(f"TCP connect: {tcp_ms:.1f} ms")
    except Exception as exc:
        print(f"TCP connect failed: {exc}")

    try:
        http_ms = measure_http(url)
        print(f"HTTP GET: {http_ms:.1f} ms ({url})")
    except Exception as exc:
        print(f"HTTP GET failed: {exc}")
        if url.endswith("/health"):
            fallback = "https://clob.polymarket.com/"
            try:
                http_ms = measure_http(fallback)
                print(f"HTTP GET: {http_ms:.1f} ms ({fallback})")
            except Exception as exc2:
                print(f"HTTP GET failed: {exc2}")


if __name__ == "__main__":
    main()
