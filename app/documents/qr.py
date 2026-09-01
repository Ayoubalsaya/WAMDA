"""رمز QR مضمَّن (Base64 PNG) داخل قوالب المستندات — لا رابط خارجي مُحمَّل
في وقت العرض، الصورة جزء من الـHTML نفسه."""

from __future__ import annotations

import base64
import io

import qrcode


def qr_data_uri(data: str) -> str:
    img = qrcode.make(data, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
