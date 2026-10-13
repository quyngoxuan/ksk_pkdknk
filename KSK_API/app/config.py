from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    app_name: str = "KSK API"
    app_env: str = "development"
    sql_server: str
    sql_database: str = "PKNK_KSK"
    sql_username: str
    sql_password: str
    sql_driver: str = "SQL Server Native Client 11.0"
    sql_trust_server_certificate: str = "yes"
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"
    lien_thong_base_url: str = "https://api-hssk.hanoi.gov.vn"
    lien_thong_username: str = "01042_lt_tuyennta"
    lien_thong_password: str = "Ngockhanh!@#2022"
    lien_thong_sender_id: str = "8934287000076"
    lien_thong_receiver_id: str = "VTS"
    lien_thong_version: str = "1.0"
    lien_thong_timeout_seconds: int = 30
    lien_thong_batch_retention_days: int = 90
    lien_thong_batch_api_key: str = Field(default="", validation_alias="KSK_BATCH_API_KEY")
    lien_thong_exam_type_code: str = "01"
    lien_thong_facility_code: str = ""
    lien_thong_facility_gln: str = ""
    lien_thong_conclusion_signature_base64: str = ""
    lien_thong_facility_signature_base64: str = ""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    @property
    def database_url(self) -> str:
        connection = (
            f"DRIVER={{{self.sql_driver}}};SERVER={self.sql_server};DATABASE={self.sql_database};"
            f"UID={self.sql_username};PWD={self.sql_password};"
            f"TrustServerCertificate={self.sql_trust_server_certificate};"
        )
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(connection)}"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
