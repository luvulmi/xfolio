"""로컬 인증서·HTTPS reverse proxy 준비 검증. Google 로그인 성공 시험은 아니다."""

import http.client
import importlib.util
import json
import socket
import ssl
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "dev" / f"{name}.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


https = module("local_https")
runner = module("run_api")


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_certificate_cached_and_scoped_to_localhost():
    (ROOT / ".cache").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=ROOT / ".cache", prefix="https_test_"
    ) as directory:
        cert_path, key_path = https.ensure_certificate(directory)
        original = key_path.read_bytes()
        assert https.ensure_certificate(directory) == (cert_path, key_path)
        assert key_path.read_bytes() == original
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        assert "localhost" in cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.DNSName)
        assert cert.issuer == cert.subject
    with pytest.raises(ValueError, match="cache"):
        https.ensure_certificate(ROOT / "data" / "forbidden-cert")


@pytest.mark.parametrize(
    "target",
    [
        "https://127.0.0.1:8000",
        "http://example.invalid:8000",
        "http://user:secret@localhost:8000",
        "http://localhost:8000/path",
        "http://localhost:8000?token=secret",
    ],
)
def test_proxy_target_is_fixed_loopback_origin(target):
    with pytest.raises(ValueError):
        https.validate_target(target)


class FakeApi(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header(
            "Set-Cookie",
            "xfolio_session=fake-test; Secure; HttpOnly; SameSite=lax; Path=/api",
        )
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "path": self.path,
                    "proto": self.headers.get("X-Forwarded-Proto"),
                    "cookie": self.headers.get("Cookie"),
                }
            ).encode()
        )

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "body": json.loads(body),
                    "origin": self.headers.get("Origin"),
                    "csrf": self.headers.get("X-CSRF-Token"),
                }
            ).encode()
        )

    def log_message(self, *args):
        return


def test_verified_https_serves_spa_and_preserves_session_csrf(tmp_path, capsys):
    (tmp_path / "index.html").write_text("<h1>XFolio test</h1>", encoding="utf-8")
    (ROOT / ".cache").mkdir(exist_ok=True)
    with (
        tempfile.TemporaryDirectory(
            dir=ROOT / ".cache", prefix="https_test_"
        ) as directory,
        running(ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)) as backend,
    ):
        proxy, cert = https.make_server(
            0, f"http://127.0.0.1:{backend.server_port}", tmp_path, directory
        )
        with running(proxy):
            conn = http.client.HTTPSConnection(
                "localhost",
                proxy.server_port,
                context=ssl.create_default_context(cafile=str(cert)),
            )
            conn.request("GET", "/drafts/test")
            result = conn.getresponse()
            assert result.status == 200 and b"XFolio test" in result.read()
            conn.request(
                "GET",
                "/api/auth/me?code=not-for-logs",
                headers={"Cookie": "xfolio_session=fake-test"},
            )
            result = conn.getresponse()
            assert result.status == 200 and "Secure" in result.getheader("Set-Cookie")
            payload = json.loads(result.read())
            assert (
                payload["proto"] == "https"
                and payload["cookie"] == "xfolio_session=fake-test"
            )
            origin = f"https://localhost:{proxy.server_port}"
            conn.request(
                "POST",
                "/api/drafts/test/decision",
                body=json.dumps({"action": "hold"}),
                headers={
                    "Content-Type": "application/json",
                    "Origin": origin,
                    "X-CSRF-Token": "test-csrf",
                },
            )
            payload = json.loads(conn.getresponse().read())
            assert payload == {
                "body": {"action": "hold"},
                "origin": origin,
                "csrf": "test-csrf",
            }
            conn.close()
    assert "not-for-logs" not in capsys.readouterr().err


def test_idle_tcp_connection_does_not_block_other_tls_requests(tmp_path):
    (tmp_path / "index.html").write_text("XFolio TLS concurrency", encoding="utf-8")
    (ROOT / ".cache").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=ROOT / ".cache", prefix="https_test_"
    ) as directory:
        proxy, cert = https.make_server(0, static_dir=tmp_path, cert_dir=directory)
        with running(proxy):
            idle = socket.create_connection(("127.0.0.1", proxy.server_port), timeout=2)
            active = http.client.HTTPSConnection(
                "localhost",
                proxy.server_port,
                context=ssl.create_default_context(cafile=str(cert)),
                timeout=2,
            )
            try:
                active.request("GET", "/")
                response = active.getresponse()
                assert response.status == 200
                assert b"XFolio TLS concurrency" in response.read()
            finally:
                idle.close()
                active.close()


def test_configuration_reuse_is_explicit_and_kept_in_memory(tmp_path, monkeypatch):
    secret_file = tmp_path / "secrets.toml"
    secret_file.write_text(
        'XFOLIO_DATABASE_URL="postgresql://preview-invalid"\nXFOLIO_ADMIN_EMAILS=["test@example.invalid"]\n[auth]\nclient_id="test-id"\nclient_secret="test-secret"\nredirect_uri="https://old.invalid"\ncookie_secret="old-cookie"\n',
        encoding="utf-8",
    )
    for name in (
        "XFOLIO_GOOGLE_CLIENT_ID",
        "XFOLIO_GOOGLE_CLIENT_SECRET",
        "XFOLIO_ALLOWED_EMAILS",
        "XFOLIO_API_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="isolated"):
        runner.development_settings("https://localhost:8443", True, secret_file)
    monkeypatch.setenv("XFOLIO_API_DATABASE_URL", "postgresql://isolated-test-only")
    with pytest.raises(ValueError, match="google_auth"):
        runner.development_settings("https://localhost:8443", False, secret_file)
    settings = runner.development_settings("https://localhost:8443", True, secret_file)
    assert (
        settings.google_client_id == "test-id"
        and settings.google_client_secret == "test-secret"
    )
    assert settings.database_url == "postgresql://isolated-test-only"
    assert (
        settings.origin == "https://localhost:8443"
        and len(settings.cursor_secret) >= 32
    )
    assert "XFOLIO_GOOGLE_CLIENT_SECRET" not in __import__("os").environ
