"""REMIT_OUT يُعرَض «إرسال خارجي» في كل مكان (قرار مالك ٢٠٢٦-٠٩-٢٦ — ألغينا
المستفيدين نهائياً). حارس ثابت: العبارة القديمة «إرسال لمستفيد» يجب ألا تظهر
في أي ملصق واجهة أو مستند؛ الاستثناء الوحيد اسم مستعار مقبول في بحث
parseSearchQuery (مُدخَل قديم يبقى مفهوماً لا ملصقاً معروضاً)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_LABEL = "إرسال لمستفيد"
SCAN_DIRS = [ROOT / "frontend" / "src", ROOT / "app" / "documents", ROOT / "app" / "engine"]
ALLOWED = {ROOT / "frontend" / "src" / "lib" / "parseSearchQuery.ts"}


def test_old_beneficiary_label_is_gone_everywhere():
    offenders: list[str] = []
    for base in SCAN_DIRS:
        for path in base.rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".py"} or path in ALLOWED:
                continue
            if OLD_LABEL in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"«{OLD_LABEL}» ما زالت في: {offenders}"


def test_search_keeps_old_alias_and_new_label():
    text = (ROOT / "frontend" / "src" / "lib" / "parseSearchQuery.ts").read_text(encoding="utf-8")
    assert "'إرسال خارجي': 'REMIT_OUT'" in text
    assert "'إرسال لمستفيد': 'REMIT_OUT'" in text


def test_receipt_and_report_labels_use_new_name():
    for rel in ("receipt.py", "reports_doc.py", "statement.py"):
        text = (ROOT / "app" / "documents" / rel).read_text(encoding="utf-8")
        assert "إرسال خارجي" in text, rel
