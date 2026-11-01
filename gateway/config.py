"""The proxy's config file (TOML). Everything an operator sets lives here.

    [upstream]
    url = "https://api.openai.com/v1/chat/completions"
    api_key_env = "OPENAI_API_KEY"   # optional: the environment variable holding the provider's key
    timeout_seconds = 120            # longest the provider may stay silent, before the reply or between chunks

    [limits]
    requests_per_minute = 60
    tokens_per_minute = 90000        # optional
    default_max_tokens = 1024        # output allowance for a request that sets none
    max_rate_limit_retries = 3       # provider 429s retried per request before the client gets the 429
    adaptive = true                  # slow down when the provider returns 429, recover as calls succeed

    [server]                         # optional
    host = "127.0.0.1"
    port = 8080

    [credits]                        # optional; used when there are tenants
    pool = 60.0                      # credits per second across all tenants; default: requests_per_minute
    cap_seconds = 60.0               # seconds of credit a tenant can bank

    [database]                       # optional: without it nothing survives a restart
    url_env = "DATABASE_URL"         # the environment variable holding the Postgres URL
    balance_save_seconds = 5         # how often credit balances are saved

    [[tenants]]                      # none: the proxy is open and has no budgets (local use)
    id = "acme"
    share = 2.0                      # its slice of the credit pool, relative to the other tenants
    api_keys = ["sk-hermes-..."]

The default pool is the request limit because one slice a second sold at the
scorer's typical 60 credits costs 60 credits a second, and a slice comes every
60/requests_per_minute seconds. Keys are kept as hashes once loaded.
"""

import hashlib
import os
import tomllib
from dataclasses import dataclass, field


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Tenant:
    id: str
    share: float = 1.0


@dataclass(frozen=True)
class Config:
    upstream_url: str
    requests_per_minute: float
    upstream_key: str | None = None
    tokens_per_minute: float | None = None
    default_max_tokens: int = 1024
    max_rate_limit_retries: int = 3
    adaptive: bool = True
    timeout_seconds: float = 120.0
    host: str = "127.0.0.1"
    port: int = 8080
    pool: float | None = None
    cap_seconds: float = 60.0
    database_url: str | None = None
    balance_save_seconds: float = 5.0
    tenants: list[Tenant] = field(default_factory=list)
    keys: dict[str, Tenant] = field(default_factory=dict)  # sha256 of an API key -> its tenant


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _positive(value, name: str, kind=(int, float)):
    if isinstance(value, bool) or not isinstance(value, kind) or value <= 0:
        raise ConfigError(f"{name} must be a positive number")
    return value


def _non_negative(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{name} must be a whole number, 0 or more")
    return value


def _boolean(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false")
    return value


def load(path, environ=os.environ) -> Config:
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from None
    upstream, limits, server, credits, database = (raw.get(k, {}) for k in ("upstream", "limits", "server", "credits", "database"))
    if not isinstance(upstream.get("url"), str) or not upstream["url"].startswith(("http://", "https://")):
        raise ConfigError("upstream.url must be an http(s) URL")
    key = None
    if (env := upstream.get("api_key_env")) is not None:
        if not environ.get(env):
            raise ConfigError(f"upstream.api_key_env names {env}, which is not set")
        key = environ[env]
    database_url = None
    if (env := database.get("url_env")) is not None:
        if not environ.get(env):
            raise ConfigError(f"database.url_env names {env}, which is not set")
        database_url = environ[env]
    tenants, keys = [], {}
    for entry in raw.get("tenants", []):
        tenant = Tenant(entry.get("id"), _positive(entry.get("share", 1.0), "a tenant's share"))
        if not isinstance(tenant.id, str) or not tenant.id or any(t.id == tenant.id for t in tenants):
            raise ConfigError("every tenant needs a unique id")
        if not entry.get("api_keys"):
            raise ConfigError(f"tenant {tenant.id} needs at least one api key")
        for api_key in entry["api_keys"]:
            if not isinstance(api_key, str) or not api_key or hash_key(api_key) in keys:
                raise ConfigError(f"tenant {tenant.id} has an empty key or one that another tenant uses")
            keys[hash_key(api_key)] = tenant
        tenants.append(tenant)
    return Config(
        upstream_url=upstream["url"],
        upstream_key=key,
        requests_per_minute=_positive(limits.get("requests_per_minute"), "limits.requests_per_minute"),
        tokens_per_minute=None if "tokens_per_minute" not in limits else _positive(limits["tokens_per_minute"], "limits.tokens_per_minute"),
        default_max_tokens=_positive(limits.get("default_max_tokens", 1024), "limits.default_max_tokens", int),
        max_rate_limit_retries=_non_negative(limits.get("max_rate_limit_retries", 3), "limits.max_rate_limit_retries"),
        adaptive=_boolean(limits.get("adaptive", True), "limits.adaptive"),
        timeout_seconds=_positive(upstream.get("timeout_seconds", 120.0), "upstream.timeout_seconds"),
        host=server.get("host", "127.0.0.1"),
        port=_positive(server.get("port", 8080), "server.port", int),
        pool=None if "pool" not in credits else _positive(credits["pool"], "credits.pool"),
        cap_seconds=_positive(credits.get("cap_seconds", 60.0), "credits.cap_seconds"),
        database_url=database_url,
        balance_save_seconds=_positive(database.get("balance_save_seconds", 5.0), "database.balance_save_seconds"),
        tenants=tenants,
        keys=keys,
    )
