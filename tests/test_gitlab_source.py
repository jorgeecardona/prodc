"""GitLabSource: resolves a GitLab issue locator without hitting the network.

All tests inject a fake ``_fetcher`` so no real HTTP call is made. The fetcher
signature is ``(url: str, token: str) -> (http_status: int, body: object)``.
"""

from __future__ import annotations

import pytest

from prodc.adapters import GitLabSource

# ---------------------------------------------------------------------------
# Fake fetcher helpers
# ---------------------------------------------------------------------------

_ISSUE_200 = {
    "iid": 38,
    "title": "GitLab integration spec",
    "author": {"username": "jorge"},
    "created_at": "2026-09-01T12:00:00Z",
    "state": "opened",
}


def _fetch_200(url: str, token: str) -> tuple[int, object]:
    return 200, _ISSUE_200


def _fetch_404(url: str, token: str) -> tuple[int, object]:
    return 404, {"message": "404 Not found"}


def _fetch_401(url: str, token: str) -> tuple[int, object]:
    return 401, {"message": "401 Unauthorized"}


def _fetch_unreachable(url: str, token: str) -> tuple[int, object]:
    raise OSError("Name or service not known")


# ---------------------------------------------------------------------------
# Happy-path: issue exists
# ---------------------------------------------------------------------------


def test_exists_returns_ok_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_200,
    )
    r = adapter.resolve("#38")
    assert r.ok is True
    assert "#38" in r.detail
    assert "GitLab integration spec" in r.detail
    assert "jorge" in r.detail
    assert "2026-09-01" in r.detail


def test_inline_project_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Payload ``group/proj#38`` overrides the adapter's default project."""
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    called: list[str] = []

    def spy_fetch(url: str, token: str) -> tuple[int, object]:
        called.append(url)
        return 200, _ISSUE_200

    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="default/project",
        token_env="GITLAB_TOKEN",
        _fetcher=spy_fetch,
    )
    r = adapter.resolve("other/repo#38")
    assert r.ok is True
    assert "other%2Frepo" in called[0]  # URL-encoded override project used


# ---------------------------------------------------------------------------
# Not found: flagged as BROKEN source
# ---------------------------------------------------------------------------


def test_not_found_returns_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_404,
    )
    r = adapter.resolve("#99")
    assert r.ok is False
    assert "not found" in r.detail.lower()


# ---------------------------------------------------------------------------
# Missing token: graceful (not a false miss)
# ---------------------------------------------------------------------------


def test_missing_token_returns_ok_true_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the env var is absent the source is unverified, NOT flagged BROKEN."""
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_200,  # would succeed if reached — must not be called
    )
    r = adapter.resolve("#1")
    assert r.ok is True
    assert "unverified" in r.detail
    assert "GITLAB_TOKEN" in r.detail


# ---------------------------------------------------------------------------
# Auth failure: graceful (not a false miss)
# ---------------------------------------------------------------------------


def test_auth_failure_returns_ok_true_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "bad-token")
    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_401,
    )
    r = adapter.resolve("#1")
    assert r.ok is True
    assert "unverified" in r.detail


# ---------------------------------------------------------------------------
# Unreachable host: graceful (not a false miss)
# ---------------------------------------------------------------------------


def test_unreachable_host_returns_ok_true_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "some-token")
    adapter = GitLabSource(
        base_url="https://gitlab-unreachable.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_unreachable,
    )
    r = adapter.resolve("#1")
    assert r.ok is True
    assert "unverified" in r.detail
    assert "unreachable" in r.detail.lower()


# ---------------------------------------------------------------------------
# Malformed payload
# ---------------------------------------------------------------------------


def test_no_hash_is_ok_false() -> None:
    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_200,
    )
    r = adapter.resolve("38")  # missing '#'
    assert r.ok is False
    assert "expected '#<iid>'" in r.detail


def test_non_numeric_iid_is_ok_false() -> None:
    adapter = GitLabSource(
        base_url="https://gitlab.example.com",
        project="mygroup/myproject",
        token_env="GITLAB_TOKEN",
        _fetcher=_fetch_200,
    )
    r = adapter.resolve("#abc")
    assert r.ok is False
