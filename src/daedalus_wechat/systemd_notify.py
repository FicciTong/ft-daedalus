from __future__ import annotations

import os
import socket


def notify(message: str) -> None:
    target = os.environ.get("NOTIFY_SOCKET")
    if not target:
        return
    address: str | bytes
    if target.startswith("@"):
        address = "\0" + target[1:]
    else:
        address = target
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(message.encode())
    except OSError:
        return
    finally:
        sock.close()
