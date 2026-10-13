"""A loopback-only bridge for signing with a Windows USB Token certificate.

The private key remains in the token. Windows CSP/CNG is responsible for the
PIN prompt and key operation; this process never receives a PIN or key.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


def _parse_origins() -> list[str]:
    raw = os.getenv("NCCA_SIGNER_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("NCCA_SIGNER_ORIGINS phải là danh sách origin cụ thể, không được dùng *.")
    return origins


ALLOWED_ORIGINS = _parse_origins()
MAX_CONTENT_BYTES = int(os.getenv("NCCA_SIGNER_MAX_CONTENT_BYTES", "2097152"))
THUMBPRINT_RE = re.compile(r"^[A-Fa-f0-9\s]{16,128}$")

app = FastAPI(
    title="KSK Local Signer Bridge",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=600,
)


class CertificateRead(BaseModel):
    id: str = Field(description="Thumbprint của chứng thư, dùng làm certificate_id khi ký")
    subject: str
    issuer: str
    serial_number: str
    valid_from: str
    valid_to: str
    friendly_name: str | None = None


class CertificatesResponse(BaseModel):
    certificates: list[CertificateRead]


class SignRequest(BaseModel):
    certificate_id: str = Field(min_length=16, max_length=128)
    content: str = Field(min_length=1)
    content_encoding: Literal["utf-8"] = "utf-8"
    purpose: str = Field(default="hssk-kham-suc-khoe", max_length=100)


class SignResponse(BaseModel):
    signature: str
    algorithm: Literal["RSA-SHA256"] = "RSA-SHA256"
    certificate_id: str


@dataclass
class PowerShellFailure(Exception):
    message: str


LIST_CERTIFICATES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Security
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new('My', 'CurrentUser')
try {
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
    $items = @()
    foreach ($cert in $store.Certificates) {
        if (-not $cert.HasPrivateKey) { continue }
        $rsa = $null
        try {
            $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
            if ($null -eq $rsa) { continue }
            $items += [PSCustomObject]@{
                id = $cert.Thumbprint
                subject = $cert.Subject
                issuer = $cert.Issuer
                serial_number = $cert.SerialNumber
                valid_from = $cert.NotBefore.ToUniversalTime().ToString('o')
                valid_to = $cert.NotAfter.ToUniversalTime().ToString('o')
                friendly_name = if ($cert.FriendlyName) { $cert.FriendlyName } else { $null }
            }
        }
        catch {
            # A non-RSA or inaccessible certificate is not exposed by this bridge.
            continue
        }
        finally {
            if ($null -ne $rsa) { $rsa.Dispose() }
        }
    }
    [PSCustomObject]@{ certificates = @($items) } | ConvertTo-Json -Compress -Depth 3
}
finally {
    $store.Close()
}
"""


SIGN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Security
$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) { throw 'Thiếu dữ liệu yêu cầu ký.' }
$request = $raw | ConvertFrom-Json
if ($request.content_encoding -ne 'utf-8') { throw 'Bridge chỉ chấp nhận nội dung UTF-8.' }
$thumbprint = ([string]$request.certificate_id -replace '\s', '').ToUpperInvariant()
if ($thumbprint -notmatch '^[A-F0-9]{16,128}$') { throw 'certificate_id không hợp lệ.' }
$content = [string]$request.content
if ([string]::IsNullOrEmpty($content)) { throw 'Nội dung ký rỗng.' }
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new('My', 'CurrentUser')
$rsa = $null
try {
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
    $cert = @($store.Certificates | Where-Object { (($_.Thumbprint -replace '\s', '').ToUpperInvariant()) -eq $thumbprint }) | Select-Object -First 1
    if ($null -eq $cert) { throw 'Không tìm thấy chứng thư số đã chọn trong CurrentUser\\My.' }
    if (-not $cert.HasPrivateKey) { throw 'Chứng thư đã chọn không có private key.' }
    $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
    if ($null -eq $rsa) { throw 'Chứng thư không hỗ trợ RSA hoặc Windows không truy cập được private key.' }
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($content)
    $signature = $rsa.SignData(
        $bytes,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
    [PSCustomObject]@{
        signature = [System.Convert]::ToBase64String($signature)
        algorithm = 'RSA-SHA256'
        certificate_id = $cert.Thumbprint
    } | ConvertTo-Json -Compress
}
finally {
    if ($null -ne $rsa) { $rsa.Dispose() }
    $store.Close()
}
"""


def _encoded_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _run_powershell(script: str, payload: dict | None = None, *, interactive: bool = False) -> dict:
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        _encoded_powershell(script),
    ]
    if not interactive:
        command.insert(3, "-NonInteractive")
    # Certificate enumeration is silent. Signing must run in an interactive
    # Windows process so the smart-card CSP/CNG can display its PIN dialog.
    creation_flags = 0 if interactive else getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        command,
        # ASCII JSON avoids depending on the active Windows console code page.
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
        check=False,
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        # CSP errors can include certificate-specific information; do not expose them to the browser.
        raise PowerShellFailure("Windows CSP/CNG không thể thực hiện yêu cầu. Kiểm tra USB Token, chứng thư và cửa sổ nhập PIN.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PowerShellFailure("Windows CSP/CNG trả về dữ liệu không hợp lệ.") from error


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin không được phép yêu cầu ký số trên USB Token.",
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "store": "CurrentUser/My", "algorithm": "RSA-SHA256"}


@app.get("/certificates", response_model=CertificatesResponse, dependencies=[Depends(require_trusted_origin)])
def list_certificates() -> CertificatesResponse:
    try:
        data = _run_powershell(LIST_CERTIFICATES_SCRIPT)
        return CertificatesResponse.model_validate(data)
    except PowerShellFailure as error:
        raise HTTPException(status_code=503, detail=error.message) from error


@app.post("/sign", response_model=SignResponse, dependencies=[Depends(require_trusted_origin)])
def sign(payload: SignRequest) -> SignResponse:
    if not THUMBPRINT_RE.fullmatch(payload.certificate_id):
        raise HTTPException(status_code=422, detail="certificate_id phải là thumbprint của chứng thư.")
    if len(payload.content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="Nội dung ký vượt quá giới hạn của Local Signer Bridge.")
    try:
        result = _run_powershell(SIGN_SCRIPT, payload.model_dump(), interactive=True)
        signature = result.get("signature")
        if not isinstance(signature, str) or not signature:
            raise PowerShellFailure("Windows CSP/CNG không trả về chữ ký Base64.")
        return SignResponse(
            signature=signature,
            certificate_id=str(result.get("certificate_id") or payload.certificate_id),
        )
    except PowerShellFailure as error:
        raise HTTPException(status_code=503, detail=error.message) from error
