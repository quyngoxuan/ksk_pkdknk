"""Apply the idempotent current-linkage-status migration to the configured KSK database."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.database import engine
from deploy_lienthong_batch import split_batches


def main() -> None:
    settings = get_settings()
    migration = Path(__file__).resolve().parents[2] / "deploy_lienthong_exam_status.sql"
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        for batch in split_batches(migration.read_text(encoding="utf-8-sig")):
            cursor.execute(batch)
            while cursor.nextset():
                pass
        connection.commit()
        print(f"Migration completed: HealthExams linkage status in {settings.sql_database}.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
