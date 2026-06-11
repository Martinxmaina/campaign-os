import base64, hashlib, hmac, json


def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_jwt_structure_and_signature():
    from providers.ghost_jwt import ghost_admin_jwt
    key_id = "1111111111111111111111aa"
    secret_hex = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    token = ghost_admin_jwt(f"{key_id}:{secret_hex}")
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))
    assert header == {"alg": "HS256", "typ": "JWT", "kid": key_id}
    assert payload["aud"] == "/admin/"
    assert payload["exp"] - payload["iat"] == 300
    expected = hmac.new(bytes.fromhex(secret_hex),
                        f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    assert _b64url_decode(sig_b64) == expected


def test_jwt_rejects_malformed_key():
    import pytest
    from providers.ghost_jwt import ghost_admin_jwt
    with pytest.raises(ValueError):
        ghost_admin_jwt("no-colon-here")
