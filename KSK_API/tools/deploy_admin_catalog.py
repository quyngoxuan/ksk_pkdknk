"""Apply deploy_admin_catalog_2025.sql to the configured PKNK_KSK database."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.database import engine


def main() -> None:
    settings = get_settings()
    if settings.sql_database.casefold() != "pknk_ksk":
        raise SystemExit(f"Refusing to deploy to unexpected database: {settings.sql_database}")
    migration = Path(__file__).resolve().parents[2] / "deploy_admin_catalog_2025.sql"
    sql = migration.read_text(encoding="utf-8-sig")
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        result = None
        while True:
            if cursor.description:
                result = cursor.fetchone()
            if not cursor.nextset():
                break
        connection.commit()
        if result:
            print(f"ActiveProvinces={result[0]}, ActiveWards={result[1]}")
        else:
            print("Migration completed; no count result returned.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
