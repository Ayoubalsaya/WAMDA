"""بيئة Jinja2 مشتركة لكل قوالب المستندات (§٨) — قالب واحد لكل نوع مستند
يُستخدَم لكل المخرجات الثلاثة (PDF A4 · PDF ٨٠مم حراري · PNG)، والفرق بين
المخرجات مُتحكَّم فيه بمتغيّر `doc_size` داخل نفس القالب (`@page`/عرض
الحاوية)، لا قوالب منفصلة لكل مقاس."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_template(name: str, **context) -> str:
    return env.get_template(name).render(**context)
