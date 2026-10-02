from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

# الحدّ الصارم الإلزامي حين APP_ENV=production (طلب مالك صريح، ٢٠٢٦-١٠-٠٢):
# قيمة أضعف من هذا في الإنتاج ترفض الإقلاع كلياً — لا تصحيح صامت. محلياً
# (APP_ENV!=production) القيم حرة كما هي بلا أي قيد.
PRODUCTION_MAX_LOGIN_RATE_LIMIT = 5
PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS = 900  # ١٥ دقيقة


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    work_timezone: str = "Africa/Tripoli"
    app_env: str = "local"
    # §٨ — رمز QR في المستندات المولَّدة (تحقق/فتح البوابة) يحتاج عنواناً
    # مطلقاً قابلاً للمسح من هاتف؛ localhost لا يعمل فعلياً من جهاز آخر،
    # هذا افتراض تطوير محلي فقط — يُضبَط في `.env` عند النشر الفعلي (قرار
    # مالك معلَّق: طريقة الوصول للسيرفر، انظر PROGRESS.md).
    public_base_url: str = "http://127.0.0.1:8000"

    # §٩ — النسخ الاحتياطي: وجهة الرفع خارج السيرفر **قرار مالك معلَّق**
    # (انظر PROGRESS.md، "النطاق الفرعي ووجهة النسخ الاحتياطي"). بُنيت
    # آلية عامة قابلة للضبط بدل افتراض مزوّد سحابي بعينه: مجلد "خارج
    # السيرفر" (مسار مُركَّب فعلياً — rclone mount أو محرك شبكي، اختيار
    # المالك) و/أو SFTP كبديل شبكي مباشر، كلاهما اختياري ومُعطَّل افتراضياً
    # (بلا ضبط = بلا رفع خارجي فعلي، يُطبَع تحذير صريح لا فشل صامت).
    backup_encryption_key: Optional[str] = None  # Fernet — مطلوب فعلياً وقت التشغيل لا وقت الإقلاع
    backup_offsite_dir: Optional[str] = None
    backup_sftp_host: Optional[str] = None
    backup_sftp_port: int = 22
    backup_sftp_user: Optional[str] = None
    backup_sftp_key_path: Optional[str] = None
    backup_sftp_remote_dir: Optional[str] = None
    # أدوات pg_dump/pg_restore على PATH افتراضياً (خادم لينكس الحقيقي عبر
    # apt) — هذا التجاوز لبيئة تطوير ويندوز محلية حيث لا تكون على PATH
    pg_dump_path: Optional[str] = None
    pg_restore_path: Optional[str] = None
    psql_path: Optional[str] = None
    # اتصال منفصل بصلاحية CREATEDB لاختبار الاستعادة إلى قاعدة مؤقتة —
    # افتراضياً نفس database_url (يعمل هنا لأن wamda_app مُنحت CREATEDB
    # صراحة لهذا الغرض)، قابل للفصل عن اتصال التطبيق الفعلي في بيئة أكثر
    # صرامة بفصل الصلاحيات.
    backup_admin_database_url: Optional[str] = None

    # §٩ المرحلة ١٢ — تحديد معدل مسارات الدخول (لكل عنوان IP، نافذة منزلقة).
    # الموظف: عنوان ثابت غالباً → حدّ أضيق. العميل: هاتف بشبكة متغيّرة →
    # حدّ أوسع. يُطبَّق على تسجيل الدخول فقط، لا أي طلب قراءة.
    login_rate_limit_max: int = 10
    portal_login_rate_limit_max: int = 30
    login_rate_limit_window_seconds: int = 300
    # الثقة بترويسات الوكيل (`X-Real-IP`/`X-Forwarded-For`) لتحديد عنوان
    # العميل. **يجب أن يبقى False محلياً**: الثقة العمياء تسمح لأي أحد
    # بتزوير عنوانه وتجاوز الحدّ. يُفعَّل في `.env` على السيرفر **فقط** حين
    # يكون خلف nginx يضبط هذه الترويسات فعلاً (انظر README). بلا تفعيله
    # خلف nginx: كل الطلبات من 127.0.0.1 فيُقفَل الحدّ على الجميع.
    trust_proxy_headers: bool = False

    @model_validator(mode="after")
    def _enforce_production_rate_limit_floor(self) -> "Settings":
        if self.app_env != "production":
            return self
        violations: list[str] = []
        if self.login_rate_limit_max > PRODUCTION_MAX_LOGIN_RATE_LIMIT:
            violations.append(
                f"LOGIN_RATE_LIMIT_MAX={self.login_rate_limit_max} يتجاوز الحدّ "
                f"الصارم المسموح في الإنتاج ({PRODUCTION_MAX_LOGIN_RATE_LIMIT})"
            )
        if self.portal_login_rate_limit_max > PRODUCTION_MAX_LOGIN_RATE_LIMIT:
            violations.append(
                f"PORTAL_LOGIN_RATE_LIMIT_MAX={self.portal_login_rate_limit_max} يتجاوز "
                f"الحدّ الصارم المسموح في الإنتاج ({PRODUCTION_MAX_LOGIN_RATE_LIMIT})"
            )
        if self.login_rate_limit_window_seconds < PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS:
            violations.append(
                f"LOGIN_RATE_LIMIT_WINDOW_SECONDS={self.login_rate_limit_window_seconds} "
                f"أقلّ من الحدّ الأدنى المسموح في الإنتاج "
                f"({PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS})"
            )
        if violations:
            raise ValueError(
                "رفض الإقلاع — APP_ENV=production يفرض حدّاً صارماً على معدّل "
                "محاولات الدخول: " + " · ".join(violations)
            )
        return self


settings = Settings()
