"""Configuration validation without network side effects."""

import ipaddress
import math
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from .languages import resolve_chain


@dataclass(frozen=True)
class Settings:
    chain: tuple[str, ...]
    preset: str | None = "long"
    mode: str = "faithful"
    repeat: int = 1
    endpoint: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen2.5:7b"
    timeout: float = 120.0
    retries: int = 0
    temperature: float | None = None
    api_key: str | None = field(default=None, repr=False)

    def request_settings(self) -> dict:
        settings = {"timeout": self.timeout, "retries": self.retries}
        if self.temperature is not None:
            settings["temperature"] = self.temperature
        return settings


def normalize_endpoint(value: str) -> str:
    invalid = ValueError("endpoint must be an HTTP(S) API base URL without credentials, query, or fragment")
    if not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise invalid
    try:
        if "://" not in value:
            bare = urlsplit("//" + value)
            host = bare.hostname
            loopback = host == "localhost"
            if not loopback:
                loopback = ipaddress.ip_address(host or "").is_loopback
            if not loopback or bare.port is None:
                raise invalid
            value = "http://" + value
        parsed = urlsplit(value)
        port = parsed.port  # Validate numeric range, even for explicit URLs.
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or "?" in value or "#" in value or port == 0):
            raise invalid
        path = parsed.path.rstrip("/") or "/v1"
        if path.endswith("/chat/completions"):
            raise ValueError("endpoint must be an API base URL, not a chat/completions operation URL")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    except (ValueError, TypeError):
        raise invalid from None


def resolve_settings(options: Namespace, environ: Mapping[str, str]) -> Settings:
    def value(name, default, env=None):
        supplied = getattr(options, name, None)
        return supplied if supplied is not None else environ.get(env, default) if env else default

    preset, chain = getattr(options, "preset", None), getattr(options, "chain", None)
    languages = resolve_chain(preset, chain)
    mode = value("mode", "faithful", "CONVOLUTE_MODE")
    if mode not in ("faithful", "creative"):
        raise ValueError("mode must be faithful or creative")
    model = value("model", "qwen2.5:7b", "CONVOLUTE_MODEL")
    if not model.strip():
        raise ValueError("model must not be empty")
    repeat, retries = value("repeat", 1), value("retries", 0)
    if type(repeat) is not int or repeat <= 0:
        raise ValueError("repeat must be a positive integer")
    if type(retries) is not int or retries < 0:
        raise ValueError("retries must be a nonnegative integer")
    timeout, temperature = value("timeout", 120.0), value("temperature", None)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if temperature is not None and (not math.isfinite(temperature) or not 0 <= temperature <= 2):
        raise ValueError("temperature must be finite and between 0 and 2")
    return Settings(
        chain=languages, preset=None if chain is not None else preset or "long",
        mode=mode, repeat=repeat,
        endpoint=normalize_endpoint(value("endpoint", "http://127.0.0.1:11434/v1", "CONVOLUTE_ENDPOINT")),
        model=model.strip(), timeout=timeout, retries=retries, temperature=temperature,
        api_key=environ.get("CONVOLUTE_API_KEY") or None,
    )
