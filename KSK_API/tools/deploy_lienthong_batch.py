"""Apply the idempotent batch tracking migration to the configured KSK database."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.database import engine


def split_batches(sql: str) -> list[str]:
    batches: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        if line.strip().casefold() == "go":
            if any(part.strip() for part in current):
                batches.append("\n".join(current))
            current.clear()
        else:
            current.append(line)
    if any(part.strip() for part in current):
        batches.append("\n".join(current))
    return batches


def main() -> None:
    settings = get_settings()
    if settings.sql_database.casefold() != "pknk_ksk":
        raise SystemExit(f"Refusing to deploy to unexpected database: {settings.sql_database}")
    migration = Path(__file__).resolve().parents[2] / "deploy_lienthong_batch.sql"
    batches = split_batches(migration.read_text(encoding="utf-8-sig"))
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        for batch in batches:
            cursor.execute(batch)
            while cursor.nextset():
                pass
        connection.commit()
        print("Migration completed: LienThongBatch and LienThongBatchItem.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
