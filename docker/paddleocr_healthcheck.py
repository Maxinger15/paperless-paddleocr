"""Return success when the local PaddleX server has opened its TCP port."""

from __future__ import annotations

import socket
import sys


def main() -> int:
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=2):
            return 0
    except OSError as error:
        print(f"PaddleX TCP listener is not ready: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
