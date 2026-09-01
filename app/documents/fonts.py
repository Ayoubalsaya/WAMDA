"""تضمين خط IBM Plex Sans Arabic محلياً في كل مستند مولَّد — بلا CDN، بلا
اعتماد على خطوط النظام في بيئة النشر (§٨ قاعدة إلزامية: "الخط مضمّن
محلياً"). الملفات نفسها في `app/static/fonts/` (مصدرها حزمة npm الرسمية
`@ibm/plex-sans-arabic`، ترخيص OFL-1.1 يسمح بإعادة التوزيع).

التضمين عبر Base64 data: URI مباشرة في CSS — لا مسار ملف نسبي/`file://`
يحتاج حلّ base URL من Playwright، القيمة تُحسَب مرة واحدة عند أول استيراد
وتُخزَّن بالذاكرة (fonttools ليست مطلوبة، الملفات صغيرة أصلاً: ٧٠-٧٦ كِلو
بايت لكل وزن).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"

_WEIGHTS = {
    "Regular": 400,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}


@lru_cache(maxsize=1)
def font_face_css() -> str:
    blocks = []
    for weight_name, weight_num in _WEIGHTS.items():
        path = _FONTS_DIR / f"IBMPlexSansArabic-{weight_name}.woff2"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        blocks.append(f"""
@font-face {{
    font-family: "Plex Arabic";
    font-weight: {weight_num};
    font-style: normal;
    font-display: block;
    src: url(data:font/woff2;base64,{data}) format("woff2");
}}""")
    return "\n".join(blocks)
