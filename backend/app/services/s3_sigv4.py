"""Minimal AWS Signature Version 4 for S3-compatible PUT/GET/HEAD.

Brock 2026-08-18: closes ledger #16 (off-volume backup) properly.
Cloudflare R2 speaks S3-compatible API but the existing off-volume
backup endpoint only supported pre-signed URLs. This module adds v4
signing so the backup endpoint can PUT directly to R2 using the
long-lived access-key + secret-key credentials.

Zero dependencies beyond stdlib. Correct enough for single-file
uploads to R2/S3/MinIO. Not a full S3 client — no multipart, no
streaming, no LIST.

Signed with the sha256 payload hash (safest — R2 requires payload hash
for security on unsigned-payload accounts).
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import urllib.parse
from typing import Dict, Optional


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _derive_signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def sign_request(
    *,
    method: str,
    url: str,
    payload: bytes,
    access_key: str,
    secret_key: str,
    region: str = "auto",
    service: str = "s3",
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Return the headers dict to attach to an urllib.request.Request.

    - `url` is the full endpoint including bucket + object key path.
    - `payload` is the raw bytes body (or b"" for GET/HEAD).
    - `region` is "auto" for R2, or a real region for AWS S3.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    canonical_uri = urllib.parse.quote(parsed.path, safe="/~")
    if not canonical_uri:
        canonical_uri = "/"

    canonical_query = ""
    if parsed.query:
        # Sort query params for canonical form
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        pairs.sort()
        canonical_query = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
            for k, v in pairs
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(payload).hexdigest()

    # Base headers we always sign
    signed_headers_dict = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if extra_headers:
        for k, v in extra_headers.items():
            signed_headers_dict[k.lower()] = v

    sorted_header_keys = sorted(signed_headers_dict.keys())
    canonical_headers = "".join(
        f"{k}:{signed_headers_dict[k].strip()}\n" for k in sorted_header_keys
    )
    signed_headers = ";".join(sorted_header_keys)

    canonical_request = "\n".join([
        method.upper(),
        canonical_uri,
        canonical_query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _derive_signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    auth = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    # Headers to actually send. Include content-type if caller passed one.
    out = {
        "Authorization": auth,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if extra_headers:
        for k, v in extra_headers.items():
            if k.lower() not in ("authorization", "x-amz-content-sha256", "x-amz-date"):
                out[k] = v
    return out
