import pytest
from limits.storage import MemoryStorage

import app as app_module
from app import limiter


class TestStorageUriSelection:
    def test_falls_back_to_memory_without_redis(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("REDISCLOUD_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert app_module._limiter_storage_uri() == "memory://"

    def test_uses_redis_url_when_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("REDISCLOUD_URL", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        assert app_module._limiter_storage_uri() == "redis://localhost:6379/0"

    def test_rediscloud_takes_precedence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REDISCLOUD_URL", "redis://cloud:6379/0")
        monkeypatch.setenv("REDIS_URL", "redis://local:6379/0")
        assert app_module._limiter_storage_uri() == "redis://cloud:6379/0"


class TestLimiterResilience:
    def test_in_memory_fallback_is_enabled(self) -> None:
        assert limiter._in_memory_fallback_enabled is True

    def test_storage_matches_the_environment(self) -> None:
        on_memory = isinstance(limiter.storage, MemoryStorage)
        assert on_memory == (app_module._limiter_storage_uri() == "memory://")


class TestClientAddress:
    CLOUDFLARE_PEER = "104.16.0.1"
    CLOUDFLARE_PEER_V6 = "2606:4700::1"
    OUTSIDE_PEER = "203.0.113.7"
    VISITOR = "198.51.100.42"

    def _address(self, peer: str, headers: dict[str, str] | None = None) -> str:
        with app_module.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": peer}, headers=headers or {},
        ):
            return app_module._client_address()

    def test_without_the_header_the_peer_is_used(self) -> None:
        assert self._address(self.CLOUDFLARE_PEER) == self.CLOUDFLARE_PEER

    def test_cloudflare_peer_means_the_header_is_believed(self) -> None:
        got = self._address(self.CLOUDFLARE_PEER, {"CF-Connecting-IP": self.VISITOR})
        assert got == self.VISITOR

    def test_ipv6_cloudflare_peer_is_recognised(self) -> None:
        got = self._address(self.CLOUDFLARE_PEER_V6, {"CF-Connecting-IP": self.VISITOR})
        assert got == self.VISITOR

    def test_a_forged_header_from_outside_is_ignored(self) -> None:
        got = self._address(self.OUTSIDE_PEER, {"CF-Connecting-IP": self.VISITOR})
        assert got == self.OUTSIDE_PEER

    def test_an_unparseable_header_falls_back_to_the_peer(self) -> None:
        got = self._address(
            self.CLOUDFLARE_PEER, {"CF-Connecting-IP": "not-an-address"},
        )
        assert got == self.CLOUDFLARE_PEER

    def test_whitespace_only_header_falls_back_to_the_peer(self) -> None:
        got = self._address(self.CLOUDFLARE_PEER, {"CF-Connecting-IP": "   "})
        assert got == self.CLOUDFLARE_PEER

    def test_the_limiter_uses_this_key_function(self) -> None:
        assert limiter._key_func is app_module._client_address


class TestCloudflarePeerDetection:
    @pytest.mark.parametrize(
        "address",
        ["104.16.0.1", "172.64.0.1", "131.0.72.1", "2400:cb00::1", "2a06:98c0::1"],
    )
    def test_published_ranges_are_recognised(self, address: str) -> None:
        assert app_module._is_cloudflare_peer(address) is True

    @pytest.mark.parametrize(
        "address",
        ["203.0.113.7", "127.0.0.1", "99.83.217.1", "2001:db8::1"],
    )
    def test_other_addresses_are_not(self, address: str) -> None:
        assert app_module._is_cloudflare_peer(address) is False

    @pytest.mark.parametrize("address", [None, "", "not-an-address", "999.1.1.1"])
    def test_unusable_input_is_not_cloudflare(self, address: str | None) -> None:
        assert app_module._is_cloudflare_peer(address) is False

    def test_every_published_range_parses(self) -> None:
        assert len(app_module._CLOUDFLARE_NETWORKS) == len(app_module._CLOUDFLARE_CIDRS)
