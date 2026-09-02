from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
