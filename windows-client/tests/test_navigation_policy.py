from __future__ import annotations

import pytest

from causalagent_desktop.config import NavigationAction, NavigationPolicy


@pytest.fixture()
def development_policy() -> NavigationPolicy:
    return NavigationPolicy(
        {
            "http://127.0.0.1:5001",
            "http://localhost:5001",
        }
    )


def test_same_origin_pages_stay_inside_webview(development_policy: NavigationPolicy) -> None:
    decision = development_policy.decide("http://localhost:5001/chat/session?id=7")

    assert decision.action is NavigationAction.ALLOW_INTERNAL
    assert decision.origin == "http://localhost:5001"


def test_external_https_is_sent_to_system_browser(development_policy: NavigationPolicy) -> None:
    decision = development_policy.decide("https://docs.example.test/guide")

    assert decision.action is NavigationAction.OPEN_EXTERNAL
    assert decision.normalized_url == "https://docs.example.test/guide"


@pytest.mark.parametrize(
    "url",
    [
        "http://not-allowed.example.test/",
        "file:///C:/Users/Public/test.html",
        "javascript:alert(document.cookie)",
        "mailto:person@example.test",
        "custom-scheme://example.test/path",
        "about:blank",
        "https://localhost:5001.evil.example.test/",
        "https://user:pass@docs.example.test/",
    ],
)
def test_non_whitelisted_or_unsafe_navigation_is_blocked(
    development_policy: NavigationPolicy,
    url: str,
) -> None:
    assert development_policy.decide(url).action is NavigationAction.BLOCK


def test_http_external_navigation_is_blocked_instead_of_opened(
    development_policy: NavigationPolicy,
) -> None:
    decision = development_policy.decide("http://docs.example.test/guide")

    assert decision.action is NavigationAction.BLOCK
    assert decision.reason == "non_whitelisted_http"

