from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import ssl
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request


SCHEMA_VERSION = 1
OFFICIAL_HISTORY_ENDPOINT = "https://quantapi.51ifind.com/api/v1/cmd_history_quotation"
ALLOWED_HISTORY_INDICATORS = {"open", "high", "low", "close", "volume", "amount"}
ACCESS_TOKEN_ENV = "IFIND_ACCESS_TOKEN"
SDK_USERNAME_ENV = "IFIND_USERNAME"
SDK_PASSWORD_ENV = "IFIND_PASSWORD"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class IFindGateError(RuntimeError):
    """Raised when the phase-0A safety or capability gate is not satisfied."""


@dataclass(frozen=True)
class ProbeScope:
    endpoint: str
    codes: tuple[str, ...]
    indicators: tuple[str, ...]
    start_date: date
    end_date: date
    function_parameters: dict[str, str]

    @property
    def calendar_day_count(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def validate(self) -> None:
        if self.endpoint != OFFICIAL_HISTORY_ENDPOINT:
            raise IFindGateError("The phase-0A probe endpoint must be the official iFinD history endpoint")
        if len(self.codes) != 2:
            raise IFindGateError("The phase-0A probe must contain exactly two securities")
        if not 2 <= self.calendar_day_count <= 3:
            raise IFindGateError("The phase-0A probe must span two or three calendar days")
        if not 1 <= len(self.indicators) <= 3:
            raise IFindGateError("The phase-0A probe must contain one to three indicators")
        unknown = set(self.indicators) - ALLOWED_HISTORY_INDICATORS
        if unknown:
            raise IFindGateError(f"Unsupported phase-0A history indicators: {sorted(unknown)}")
        if any(not code.endswith((".SH", ".SZ")) for code in self.codes):
            raise IFindGateError("The phase-0A probe is restricted to A-share .SH/.SZ codes")

    def request_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "codes": ",".join(self.codes),
            "indicators": ",".join(self.indicators),
            "startdate": self.start_date.isoformat(),
            "enddate": self.end_date.isoformat(),
            "functionpara": dict(sorted(self.function_parameters.items())),
        }


def load_probe_scope(path: str | Path) -> ProbeScope:
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise IFindGateError(
                "Non-JSON YAML configuration requires PyYAML; the checked-in example is JSON-compatible YAML"
            ) from exc
        payload = yaml.safe_load(text) or {}
    probe = payload.get("probe") or {}
    scope = ProbeScope(
        endpoint=str(probe.get("endpoint", "")),
        codes=tuple(str(item) for item in probe.get("codes", [])),
        indicators=tuple(str(item) for item in probe.get("indicators", [])),
        start_date=date.fromisoformat(str(probe.get("start_date"))),
        end_date=date.fromisoformat(str(probe.get("end_date"))),
        function_parameters={str(key): str(value) for key, value in (probe.get("function_parameters") or {}).items()},
    )
    scope.validate()
    return scope


def detect_local_capabilities(
    env: Mapping[str, str] | None = None,
    *,
    module_finder: Callable[[str], Any] = importlib.util.find_spec,
) -> dict[str, Any]:
    source = os.environ if env is None else env
    username_configured = bool(source.get(SDK_USERNAME_ENV))
    password_configured = bool(source.get(SDK_PASSWORD_ENV))
    return {
        "sdk_module_available": module_finder("iFinDPy") is not None,
        "sdk_username_configured": username_configured,
        "sdk_password_configured": password_configured,
        "sdk_credentials_configured": username_configured and password_configured,
        "http_access_token_configured": bool(source.get(ACCESS_TOKEN_ENV)),
        "credential_source": "environment_only",
    }


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact_text(value: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:500]


def build_preflight_manifest(
    scope: ProbeScope,
    *,
    env: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    scope.validate()
    capabilities = detect_local_capabilities(env)
    request_payload = scope.request_payload()
    token_ready = capabilities["http_access_token_configured"]
    return {
        "schema_version": SCHEMA_VERSION,
        "probe_id": "ifind-0a-history-quotes",
        "created_at_utc": _utc_now(),
        "provider": "tonghuashun_ifind",
        "transport": "http",
        "endpoint": scope.endpoint,
        "interface_or_function": "cmd_history_quotation / THS_HQ",
        "request_scope": {
            "codes": list(scope.codes),
            "indicators": list(scope.indicators),
            "start_date": scope.start_date.isoformat(),
            "end_date": scope.end_date.isoformat(),
            "calendar_day_count": scope.calendar_day_count,
            "function_parameters": dict(sorted(scope.function_parameters.items())),
        },
        "request_sha256": _canonical_sha256(request_payload),
        "local_capabilities": capabilities,
        "license": {"status": "unconfirmed", "authorized_use_acknowledged": False},
        "execution": {
            "dry_run": True,
            "execute_flag": False,
            "network_request_sent": False,
            "http_status": None,
            "latency_ms": None,
        },
        "response": None,
        "gate_status": "ready_not_executed" if token_ready else "blocked_missing_access_token",
        "failure_mode": None if token_ready else "MISSING_ACCESS_TOKEN",
        "config_path": str(config_path) if config_path else None,
        "security_controls": [
            "environment_only_credentials",
            "fixed_official_https_endpoint",
            "no_redirects",
            "tls_verification_enabled",
            "bounded_request_scope",
            "no_raw_response_persistence",
        ],
    }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_open_request(request: urllib.request.Request, timeout: float):
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _NoRedirectHandler(),
    )
    return opener.open(request, timeout=timeout)


def _root_value(payload: Any, *names: str) -> Any:
    if not isinstance(payload, dict):
        return None
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def execute_http_probe(
    scope: ProbeScope,
    access_token: str,
    *,
    timeout: float = 30.0,
    open_request: Callable[[urllib.request.Request, float], Any] = _default_open_request,
) -> dict[str, Any]:
    scope.validate()
    if not access_token:
        raise IFindGateError(f"Missing {ACCESS_TOKEN_ENV}")
    request_body = json.dumps(scope.request_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        scope.endpoint,
        data=request_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "access_token": access_token,
            "ifindlang": "cn",
        },
    )
    started = time.perf_counter()
    with open_request(request, timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        http_status = int(response.getcode())
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise IFindGateError("iFinD probe response exceeded the 2 MiB safety limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IFindGateError("iFinD probe returned a non-JSON response") from exc

    error_code = _root_value(payload, "errorcode", "error_code")
    error_message = _root_value(payload, "errmsg", "error_message", "message")
    data_volume = _root_value(payload, "dataVol", "data_volume")
    success = http_status == 200 and str(error_code) in {"0", "0.0"}
    return {
        "status": "success" if success else "remote_error",
        "http_status": http_status,
        "latency_ms": latency_ms,
        "response_size_bytes": len(raw),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_top_level_keys": sorted(str(key) for key in payload) if isinstance(payload, dict) else [],
        "ifind_error_code": error_code,
        "ifind_error_message": redact_text(error_message, (access_token,)) if error_message is not None else None,
        "data_volume": data_volume,
        "raw_response_persisted": False,
    }


def write_manifest(manifest: Mapping[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the phase-0A read-only iFinD capability gate.")
    parser.add_argument("--config", default="config/ifind_field_mapping.example.yaml")
    parser.add_argument("--output", default="ifind_probe_manifest.json")
    parser.add_argument("--execute", action="store_true", help="Send the bounded real HTTP probe.")
    parser.add_argument(
        "--acknowledge-authorized-use",
        action="store_true",
        help="Confirm that the account and requested use are authorized by the iFinD license.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    scope = load_probe_scope(args.config)
    manifest = build_preflight_manifest(scope, config_path=args.config)
    if not args.execute:
        write_manifest(manifest, args.output)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 2
    if not args.acknowledge_authorized_use:
        manifest["gate_status"] = "blocked_license_not_acknowledged"
        manifest["failure_mode"] = "UNAUTHORIZED_EXECUTION"
        write_manifest(manifest, args.output)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 2

    access_token = os.environ.get(ACCESS_TOKEN_ENV, "")
    if not access_token:
        write_manifest(manifest, args.output)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 2

    manifest["license"] = {"status": "user_acknowledged", "authorized_use_acknowledged": True}
    manifest["execution"].update({"dry_run": False, "execute_flag": True})
    try:
        result = execute_http_probe(scope, access_token, timeout=args.timeout)
        manifest["execution"].update(
            {
                "network_request_sent": True,
                "http_status": result["http_status"],
                "latency_ms": result["latency_ms"],
            }
        )
        manifest["response"] = result
        if result["status"] == "success":
            manifest["gate_status"] = "passed_minimum_http_probe"
            manifest["failure_mode"] = None
            return_code = 0
        else:
            manifest["gate_status"] = "blocked_remote_error"
            manifest["failure_mode"] = "IFIND_REMOTE_ERROR"
            return_code = 2
    except (IFindGateError, urllib.error.URLError, TimeoutError) as exc:
        manifest["execution"]["network_request_sent"] = True
        manifest["gate_status"] = "blocked_probe_failure"
        manifest["failure_mode"] = type(exc).__name__
        manifest["response"] = {"status": "failure", "message": redact_text(exc, (access_token,))}
        return_code = 2
    finally:
        write_manifest(manifest, args.output)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return return_code
