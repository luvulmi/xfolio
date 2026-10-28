"""개발용 loopback HTTPS 정적 서버와 고정 API reverse proxy.

OS 인증서 신뢰 저장소를 변경하지 않는다. 프로덕션 서버로 사용하지 않는다.
"""

import argparse
import http.client
import ipaddress
import ssl
from datetime import UTC, datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
CERT_DIR = ROOT / ".cache" / "dev_https"
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def ensure_certificate(directory=CERT_DIR):
    """개인키는 무시되는 .cache 하위에만 새로 만든다. 인증서는 30일 유효하다."""
    directory = Path(directory).resolve()
    if not directory.is_relative_to((ROOT / ".cache").resolve()):
        raise ValueError("certificate_directory_must_be_in_cache")
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "localhost.pem", directory / "localhost-key.pem"
    if cert_path.exists() and key_path.exists():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        expected = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        actual = cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        if expected == actual and cert.not_valid_after_utc > datetime.now(
            UTC
        ) + timedelta(days=1):
            return cert_path, key_path
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "XFolio localhost development")]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def validate_target(target):
    parts = urlsplit(target)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parts.username
        or parts.password
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError("api_target_must_be_loopback_http_origin")
    return parts


class DevHandler(SimpleHTTPRequestHandler):
    api_target = "http://127.0.0.1:8000"

    def log_message(self, format, *args):
        # OAuth code/state, cookie, 키, 요청 본문을 access log에 남기지 않는다.
        return

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.proxy()
        if urlsplit(self.path).scheme or not self.path.startswith("/"):
            self.send_error(400, "invalid_request_target")
            return None
        path = Path(self.translate_path(self.path))
        # React client routes resolve to index.html; static missing assets stay 404.
        if not path.is_file() and "." not in Path(urlsplit(self.path).path).name:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(405)
            return
        self.proxy()

    def proxy(self):
        target = validate_target(self.api_target)
        if self.headers.get("Transfer-Encoding"):
            self.send_error(400, "chunked_request_not_supported")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if not 0 <= length <= 1_048_576:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else None
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower()
            not in HOP_HEADERS
            | {"host", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-for"}
        }
        headers.update({"Host": target.netloc, "X-Forwarded-Proto": "https"})
        connection = http.client.HTTPConnection(
            target.hostname, target.port or 80, timeout=15
        )
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            result = connection.getresponse()
            data = result.read(4_194_305)
            if len(data) > 4_194_304:
                self.send_error(502, "api_response_too_large")
                return
            self.send_response(result.status)
            for key, value in result.getheaders():
                if key.lower() not in HOP_HEADERS | {
                    "content-length",
                    "server",
                    "date",
                    "cache-control",
                    "x-content-type-options",
                }:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.send_error(502, "api_unavailable")
        finally:
            connection.close()


def make_server(
    port=8443, api_target="http://127.0.0.1:8000", static_dir=None, cert_dir=CERT_DIR
):
    validate_target(api_target)
    static_dir = Path(static_dir or ROOT / "frontend" / "dist").resolve()
    if not (static_dir / "index.html").is_file():
        raise ValueError("frontend_build_required")
    cert, key = ensure_certificate(cert_dir)
    handler = type("ConfiguredDevHandler", (DevHandler,), {"api_target": api_target})
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), partial(handler, directory=str(static_dir))
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server, cert


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--api-target", default="http://127.0.0.1:8000")
    parser.add_argument("--cert-only", action="store_true")
    args = parser.parse_args()
    if args.cert_only:
        ensure_certificate()
        print(
            "개발 인증서를 .cache/dev_https/에 준비했습니다. OS 신뢰 설정은 변경하지 않았습니다."
        )
        return
    server, _ = make_server(args.port, args.api_target)
    print(f"XFolio 개발 HTTPS: https://localhost:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
