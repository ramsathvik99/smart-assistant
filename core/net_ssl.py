"""
Network SSL utility module.
Provides SSL contexts anchored with certifi CA bundle to prevent
CERTIFICATE_VERIFY_FAILED errors on Windows without disabling verification.
"""

import ssl
from typing import Optional

try:
    import certifi
    _CAFILE: Optional[str] = certifi.where()
except Exception:
    _CAFILE = None

_CACHED_SSL_CONTEXT: Optional[ssl.SSLContext] = None

def get_ssl_context() -> ssl.SSLContext:
    """
    Return a verified SSL context using certifi CA bundle if available.
    Verification is ALWAYS enforced (CERT_REQUIRED).
    """
    global _CACHED_SSL_CONTEXT
    if _CACHED_SSL_CONTEXT is None:
        if _CAFILE:
            ctx = ssl.create_default_context(cafile=_CAFILE)
        else:
            ctx = ssl.create_default_context()
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        _CACHED_SSL_CONTEXT = ctx
    return _CACHED_SSL_CONTEXT
