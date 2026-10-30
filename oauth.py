import base64
import hashlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import net
import secrets_store

USER_AGENT = "mcp-hub/1.0"
CLIENT_NAME = "MCP Hub"
REFRESH_MARGIN = 60

_pending = {}
_lock = threading.Lock()


class OAuthError(Exception):
    pass


def _store_name(server):
    return "oauth/" + re.sub(r"[^A-Za-z0-9._-]", "_", server)


def _request(url, data=None, headers=None, method=None):
    body = None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    if isinstance(data, dict) and headers.get("Content-Type") == "application/json":
        body = json.dumps(data).encode()
    elif isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    request = urllib.request.Request(url, body, headers, method=method or ("POST" if body else "GET"))
    try:
        with net.opener.open(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        with e:
            detail = e.read().decode(errors="replace")[:300]
        raise OAuthError(f"{url}: HTTP {e.code} {detail}".strip())
    except (OSError, ValueError) as e:
        raise OAuthError(f"{url}: {e}")


def _first_json(urls):
    for url in urls:
        try:
            return _request(url)
        except OAuthError:
            continue
    return None


def _challenge_param(challenge, key):
    match = re.search(rf'{key}="([^"]*)"', challenge or "")
    return match.group(1) if match else None


def _well_known(base, name):
    parts = urllib.parse.urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    return [f"{origin}/.well-known/{name}{path}", f"{origin}/.well-known/{name}"] if path else [f"{origin}/.well-known/{name}"]


def discover(server_url, challenge=None, settings=None):
    settings = settings or {}
    resource_meta_url = _challenge_param(challenge, "resource_metadata")
    resource = _first_json([resource_meta_url] if resource_meta_url else _well_known(server_url, "oauth-protected-resource"))
    parts = urllib.parse.urlsplit(server_url)
    issuer = ((resource or {}).get("authorization_servers") or [f"{parts.scheme}://{parts.netloc}"])[0]
    explicit = settings.get("authorizationUrl") and settings.get("tokenUrl")
    meta = None if explicit else _first_json(_well_known(issuer, "oauth-authorization-server") + _well_known(issuer, "openid-configuration"))
    meta = dict(meta or {
        "authorization_endpoint": urllib.parse.urljoin(issuer, "/authorize"),
        "token_endpoint": urllib.parse.urljoin(issuer, "/token"),
        "registration_endpoint": urllib.parse.urljoin(issuer, "/register"),
    })
    if settings.get("authorizationUrl"):
        meta["authorization_endpoint"] = settings["authorizationUrl"]
    if settings.get("tokenUrl"):
        meta["token_endpoint"] = settings["tokenUrl"]
    for key, label in (("authorization_endpoint", "The authorization endpoint"), ("token_endpoint", "The token endpoint"),
                       ("registration_endpoint", "The registration endpoint")):
        if meta.get(key) and not net.secure_url(meta[key]):
            raise OAuthError(f"{label} must use https: {meta[key]}")
    if "S256" not in meta.get("code_challenge_methods_supported", ["S256"]):
        raise OAuthError("The authorization server does not support PKCE (S256)")
    scope = settings.get("scopes") or _challenge_param(challenge, "scope") or " ".join((resource or {}).get("scopes_supported") or [])
    return {"resource": (resource or {}).get("resource") or server_url, "meta": meta, "scope": scope}


def _register(meta, redirect_uri):
    if not meta.get("registration_endpoint"):
        raise OAuthError("The provider does not offer automatic client registration. "
                         "Create an OAuth app with the provider and enter its client ID under “OAuth” in the server entry.")
    try:
        return _request(meta["registration_endpoint"], {
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        }, {"Content-Type": "application/json"})
    except OAuthError as e:
        raise OAuthError(f"Automatic client registration failed ({e}). "
                         "Create an OAuth app with the provider and enter its client ID under “OAuth” in the server entry.")


def start(server, server_url, redirect_uri, challenge=None, settings=None):
    settings = settings or {}
    found = discover(server_url, challenge, settings)
    if settings.get("clientId"):
        client = {"client_id": settings["clientId"]}
        if settings.get("clientSecret"):
            client["client_secret"] = settings["clientSecret"]
            client["token_endpoint_auth_method"] = settings.get("tokenAuth", "client_secret_post")
    else:
        stored = load(server) or {}
        client = stored.get("client") if stored.get("redirect_uri") == redirect_uri and not stored.get("client", {}).get("client_secret") else None
        client = client or _register(found["meta"], redirect_uri)
    verifier = secrets.token_urlsafe(48)
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": found["resource"],
    }
    if found["scope"]:
        params["scope"] = found["scope"]
    with _lock:
        _pending[state] = {"server": server, "verifier": verifier, "client": client, "redirect_uri": redirect_uri,
                           "resource": found["resource"], "token_endpoint": found["meta"]["token_endpoint"], "t": time.time()}
        for key in [k for k, v in _pending.items() if time.time() - v["t"] > 900]:
            _pending.pop(key)
    separator = "&" if "?" in found["meta"]["authorization_endpoint"] else "?"
    return found["meta"]["authorization_endpoint"] + separator + urllib.parse.urlencode(params)


def _token_request(token_endpoint, client, data):
    data = {**data, "client_id": client["client_id"]}
    headers = {}
    if client.get("client_secret"):
        if client.get("token_endpoint_auth_method") == "client_secret_post":
            data["client_secret"] = client["client_secret"]
        else:
            pair = f"{client['client_id']}:{client['client_secret']}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
    token = _request(token_endpoint, data, headers)
    if not token.get("access_token"):
        raise OAuthError("No access_token in the authorization server response")
    return token


def _save(server, flow, token, previous=None):
    record = {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token") or (previous or {}).get("refresh_token"),
        "expires_at": time.time() + token["expires_in"] if token.get("expires_in") else None,
        "token_endpoint": flow["token_endpoint"],
        "resource": flow["resource"],
        "client": flow["client"],
        "redirect_uri": flow["redirect_uri"],
    }
    secrets_store.store_keychain(_store_name(server), json.dumps(record, separators=(",", ":")))
    return record


def finish(state, code):
    with _lock:
        flow = _pending.pop(state, None)
    if not flow:
        raise OAuthError("Unknown or expired sign-in, please start again")
    token = _token_request(flow["token_endpoint"], flow["client"], {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": flow["redirect_uri"],
        "code_verifier": flow["verifier"],
        "resource": flow["resource"],
    })
    _save(flow["server"], flow, token)
    return flow["server"]


def load(server):
    raw = secrets_store.read_keychain(_store_name(server))
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def refresh(server):
    record = load(server)
    if not record or not record.get("refresh_token"):
        return None
    token = _token_request(record["token_endpoint"], record["client"], {
        "grant_type": "refresh_token",
        "refresh_token": record["refresh_token"],
        "resource": record["resource"],
    })
    return _save(server, record, token, record)


def access_token(server, force_refresh=False):
    record = load(server)
    if not record:
        return None
    expired = record.get("expires_at") and record["expires_at"] - REFRESH_MARGIN < time.time()
    if force_refresh or expired:
        try:
            record = refresh(server)
        except OAuthError:
            return None
    return (record or {}).get("access_token")


def status(server):
    record = load(server)
    return {"signedIn": bool(record), "expiresAt": (record or {}).get("expires_at")}


def logout(server):
    secrets_store.delete_keychain(_store_name(server))
