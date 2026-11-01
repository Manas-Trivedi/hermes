import pytest

from gateway.config import ConfigError, hash_key, load

BASE = """
[upstream]
url = "https://api.example.com/v1/chat/completions"
api_key_env = "PROVIDER_KEY"
[limits]
requests_per_minute = 60
tokens_per_minute = 90000
[[tenants]]
id = "acme"
share = 3
api_keys = ["k1", "k2"]
[[tenants]]
id = "beta"
api_keys = ["k3"]
"""


def write(tmp_path, text):
    path = tmp_path / "hermes.toml"
    path.write_text(text)
    return path


def test_a_full_config_loads_with_defaults_and_keys_kept_only_as_hashes(tmp_path):
    c = load(write(tmp_path, BASE), environ={"PROVIDER_KEY": "sk-provider"})
    assert (c.requests_per_minute, c.tokens_per_minute, c.default_max_tokens, c.port, c.upstream_key) == (60, 90000, 1024, 8080, "sk-provider")
    assert (c.max_rate_limit_retries, c.timeout_seconds) == (3, 120.0)
    assert [(t.id, t.share) for t in c.tenants] == [("acme", 3), ("beta", 1.0)]
    assert c.keys[hash_key("k2")].id == "acme" and c.keys[hash_key("k3")].id == "beta" and "k1" not in c.keys


def test_a_config_without_tenants_or_a_provider_key_is_open(tmp_path):
    c = load(write(tmp_path, BASE.split("[[tenants]]")[0].replace('api_key_env = "PROVIDER_KEY"', "")), environ={})
    assert c.tenants == [] and c.keys == {} and c.upstream_key is None


@pytest.mark.parametrize("old, new, message", [
    ('url = "https://api.example.com/v1/chat/completions"', 'url = "ftp://x"', "http"),
    ("requests_per_minute = 60", "requests_per_minute = 0", "requests_per_minute"),
    ('api_keys = ["k1", "k2"]', 'api_keys = ["k3"]', "another tenant"),  # k3 is beta's
    ('api_keys = ["k3"]', "api_keys = []", "at least one"),
    ('id = "beta"', 'id = "acme"', "unique"),
    ("share = 3", "share = -1", "share"),
])
def test_a_bad_config_is_refused_with_a_message_that_says_what_is_wrong(tmp_path, old, new, message):
    with pytest.raises(ConfigError, match=message):
        load(write(tmp_path, BASE.replace(old, new)), environ={"PROVIDER_KEY": "x"})


def test_a_provider_key_variable_that_is_not_set_fails_at_startup_not_on_the_first_call(tmp_path):
    with pytest.raises(ConfigError, match="PROVIDER_KEY"):
        load(write(tmp_path, BASE), environ={})
    with pytest.raises(ConfigError, match="TOML"):
        load(write(tmp_path, "[upstream"), environ={})


def test_the_database_url_is_read_from_the_named_variable_and_its_absence_is_loud(tmp_path):
    text = BASE.split("[[tenants]]")[0].replace('api_key_env = "PROVIDER_KEY"', "") + '[database]\nurl_env = "DB"\nbalance_save_seconds = 2\n'
    c = load(write(tmp_path, text), environ={"DB": "postgresql://x"})
    assert (c.database_url, c.balance_save_seconds) == ("postgresql://x", 2.0)
    with pytest.raises(ConfigError, match="DB"):
        load(write(tmp_path, text), environ={})


def test_a_feed_open_beyond_localhost_must_have_a_token(tmp_path):
    text = BASE.split("[[tenants]]")[0].replace('api_key_env = "PROVIDER_KEY"', "")
    c = load(write(tmp_path, text + '[feed]\nport = 8765\n'), environ={})
    assert (c.feed_host, c.feed_port, c.feed_token) == ("127.0.0.1", 8765, None)
    with pytest.raises(ConfigError, match="token"):
        load(write(tmp_path, text + '[feed]\nhost = "0.0.0.0"\nport = 8765\n'), environ={})
    c = load(write(tmp_path, text + '[feed]\nhost = "0.0.0.0"\nport = 8765\ntoken_env = "T"\n'), environ={"T": "abc"})
    assert c.feed_token == "abc"
