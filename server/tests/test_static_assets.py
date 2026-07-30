"""Serving the built frontend, and the icons alongside it.

The bug these pin: the SPA fallback answered *every* unmatched path with
index.html, so `GET /favicon.ico` returned 200 and a page of HTML. Nothing
errored, the browser simply had no icon — which is the worst kind of failure,
because the status code says everything is fine.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import FRONTEND_DIST, create_app

pytestmark = pytest.mark.skipif(
    not (FRONTEND_DIST / "index.html").exists(),
    reason="the frontend has not been built; run `npm run build` in frontend/",
)


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


ICONS = [
    ("/favicon.svg", "image/svg+xml"),
    ("/favicon.ico", None),
    ("/icon-16.png", "image/png"),
    ("/icon-32.png", "image/png"),
    ("/apple-touch-icon.png", "image/png"),
    ("/icon-192.png", "image/png"),
    ("/icon-512.png", "image/png"),
]


@pytest.mark.parametrize("path,content_type", ICONS)
def test_every_icon_is_served_as_an_image_not_the_app_shell(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert not response.content.lstrip().startswith(b"<!doctype html"), (
        f"{path} returned the SPA shell; a browser asked for an icon and got a page"
    )
    if content_type:
        assert response.headers["content-type"].startswith(content_type)


def test_the_manifest_is_json_and_names_the_icons(client):
    response = client.get("/site.webmanifest")
    assert response.status_code == 200
    body = response.json()
    assert body["name"]
    assert {icon["src"] for icon in body["icons"]} >= {"/icon-192.png", "/icon-512.png"}


def test_the_html_points_at_the_icons(client):
    html = client.get("/").text
    for reference in ("/favicon.svg", "/favicon.ico", "/apple-touch-icon.png"):
        assert reference in html, f"index.html never references {reference}"


def test_the_ico_is_a_real_icon_container(client):
    """A renamed PNG would satisfy a naive check but not Windows."""
    data = client.get("/favicon.ico").content
    assert data[:4] == b"\x00\x00\x01\x00", "not an ICO header"
    count = int.from_bytes(data[4:6], "little")
    assert count >= 3, "expected 16, 32 and 48 pixel entries"


def test_an_unknown_route_still_falls_back_to_the_app(client):
    """Client-side routes must keep working; only real files take priority."""
    response = client.get("/some/deep/spa/route")
    assert response.status_code == 200
    assert response.content.lstrip().startswith(b"<!doctype html")


@pytest.mark.parametrize(
    "path",
    [
        "/../pyproject.toml",
        "/../../README.md",
        "/..%2f..%2fREADME.md",
        "/assets/../../pyproject.toml",
    ],
)
def test_the_static_route_cannot_be_walked_out_of_the_build(client, path):
    """`path` is user-controlled, so a traversal must not escape dist/."""
    response = client.get(path)
    # Either refused outright, or harmlessly answered with the SPA shell —
    # never the contents of a file from outside the build.
    assert response.status_code in {200, 301, 307, 404}
    if response.status_code == 200:
        body = response.content.lstrip()
        assert body.startswith(b"<!doctype html")
        assert b"[project]" not in body
