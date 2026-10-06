import pytest

from app.url_safety import UnsafeURL, validate_target


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost:8000/", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/", "ftp://example.com/",
    "file:///etc/passwd", "http://user:pass@example.com/",
])
def test_blocks_internal_and_unsafe_targets(url):
    with pytest.raises(UnsafeURL):
        validate_target(url)


def test_allows_public_ip():
    assert validate_target("https://93.184.215.14/") == "https://93.184.215.14/"


def test_blocks_hostname_resolving_to_private(monkeypatch):
    monkeypatch.setattr("app.url_safety.resolve_host", lambda h: ["10.1.2.3"])
    with pytest.raises(UnsafeURL):
        validate_target("https://sneaky.example.com/")


def test_dev_override_allows_private():
    assert validate_target("http://localhost:8000/", allow_private=True)
