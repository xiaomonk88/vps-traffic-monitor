"""A real local SOCKS5 handshake, with a target name that cannot resolve locally."""
import socket
import threading
from urllib.parse import quote

from sentinel.network import client


def read_exact(sock, size):
    result = b""
    while len(result) < size:
        chunk = sock.recv(size-len(result))
        if not chunk:
            raise RuntimeError("unexpected EOF")
        result += chunk
    return result


def test_authenticated_socks_forwards_hostname_and_special_password():
    observed, errors = {}, []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(10)
    password = "secret:@/#"
    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(10)
                version, count = read_exact(conn, 2)
                methods = read_exact(conn, count)
                assert version == 5 and 2 in methods
                conn.sendall(b"\x05\x02")
                assert read_exact(conn, 1) == b"\x01"
                username = read_exact(conn, read_exact(conn, 1)[0]).decode()
                actual_password = read_exact(conn, read_exact(conn, 1)[0]).decode()
                observed.update(username=username, password=actual_password)
                conn.sendall(b"\x01\x00")
                version, command, reserved, address_type = read_exact(conn, 4)
                assert (version, command, address_type) == (5, 1, 3)
                observed["host"] = read_exact(conn, read_exact(conn, 1)[0]).decode()
                read_exact(conn, 2)
                conn.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x1f\x90")
                request = b""
                while b"\r\n\r\n" not in request:
                    request += conn.recv(4096)
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
        except BaseException as exc:
            errors.append(exc)
        finally:
            listener.close()
    thread = threading.Thread(target=serve)
    thread.start()
    port = listener.getsockname()[1]
    with client(f"socks5h://user:{quote(password, safe='')}@127.0.0.1:{port}") as http:
        response = http.get("http://unresolvable-target.invalid/healthz")
    thread.join(timeout=15)
    assert not errors
    assert response.json() == {"ok": True}
    assert observed == {"username": "user", "password": password, "host": "unresolvable-target.invalid"}
