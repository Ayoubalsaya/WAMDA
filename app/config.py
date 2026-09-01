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


settings = Settings()
