"""没有域名时用的自签名证书。桌面客户端按证书指纹校验，不依赖证书机构。"""

from __future__ import annotations

import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

VALID_DAYS = 3650


def _subject_alt_name(host: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def ensure_self_signed(directory: Path, host: str) -> tuple[Path, Path]:
    """证书已存在就直接用（指纹保持不变）；不存在才生成新的。"""
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName([_subject_alt_name(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def fingerprint(cert_path: str | Path) -> str:
    """证书 DER 编码的 SHA-256，格式 AB:CD:...，和浏览器里显示的一致。"""
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    return cert.fingerprint(hashes.SHA256()).hex(":").upper()
