"""Generate an idempotent SQL Server migration from the official catalog JSON."""

import json
import sys
from pathlib import Path


def literal(value: str) -> str:
    return "N'" + value.replace("'", "''") + "'"


def values_inserts(table: str, columns: tuple[str, ...], rows: list[tuple[str, ...]], size: int = 500) -> str:
    statements = []
    for offset in range(0, len(rows), size):
        batch = rows[offset : offset + size]
        tuples = ["(" + ",".join(literal(value) for value in row) + ")" for row in batch]
        statements.append(f"INSERT INTO {table} ({','.join(columns)}) VALUES\n    " + ",\n    ".join(tuples) + ";")
    return "\n\n".join(statements)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: generate_admin_catalog_sql.py <catalog-json> <output-sql>")
    source_path, output_path = map(Path, sys.argv[1:])
    catalog = json.loads(source_path.read_text(encoding="utf-8"))
    effective = catalog["effective_from"]
    province_rows = [(p["province_code"], p["province_name"], effective) for p in catalog["provinces"]]
    ward_rows = [(w["ward_code"], w["province_code"], w["ward_name"], w["ward_type"], effective) for w in catalog["wards"]]

    sql = [
        "/* Official 2025 administrative codes: Decision 19/2025/QD-TTg and NSO Dispatch 1027/CTK-CSCL. */",
        "SET XACT_ABORT ON;\nBEGIN TRY\n    BEGIN TRANSACTION;",
        """IF OBJECT_ID(N'dbo.AdministrativeProvinces', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AdministrativeProvinces (
        ProvinceCode VARCHAR(2) NOT NULL CONSTRAINT PK_AdministrativeProvinces PRIMARY KEY,
        ProvinceName NVARCHAR(100) NOT NULL,
        EffectiveFrom DATE NOT NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_AdministrativeProvinces_IsActive DEFAULT 1
    );
END;
IF OBJECT_ID(N'dbo.AdministrativeWards', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AdministrativeWards (
        WardCode VARCHAR(5) NOT NULL CONSTRAINT PK_AdministrativeWards PRIMARY KEY,
        ProvinceCode VARCHAR(2) NOT NULL,
        WardName NVARCHAR(150) NOT NULL,
        WardType NVARCHAR(20) NOT NULL,
        EffectiveFrom DATE NOT NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_AdministrativeWards_IsActive DEFAULT 1,
        CONSTRAINT FK_AdministrativeWards_Provinces FOREIGN KEY (ProvinceCode)
            REFERENCES dbo.AdministrativeProvinces(ProvinceCode)
    );
    CREATE INDEX IX_AdministrativeWards_ProvinceCode ON dbo.AdministrativeWards(ProvinceCode, WardName);
END;
CREATE TABLE #ProvinceSource (ProvinceCode VARCHAR(2), ProvinceName NVARCHAR(100), EffectiveFrom DATE);
CREATE TABLE #WardSource (WardCode VARCHAR(5), ProvinceCode VARCHAR(2), WardName NVARCHAR(150), WardType NVARCHAR(20), EffectiveFrom DATE);""",
        values_inserts("#ProvinceSource", ("ProvinceCode", "ProvinceName", "EffectiveFrom"), province_rows),
        """UPDATE target SET ProvinceName=source.ProvinceName, EffectiveFrom=source.EffectiveFrom, IsActive=1
FROM dbo.AdministrativeProvinces target INNER JOIN #ProvinceSource source ON source.ProvinceCode=target.ProvinceCode;
INSERT dbo.AdministrativeProvinces (ProvinceCode, ProvinceName, EffectiveFrom)
SELECT source.ProvinceCode, source.ProvinceName, source.EffectiveFrom FROM #ProvinceSource source
WHERE NOT EXISTS (SELECT 1 FROM dbo.AdministrativeProvinces target WHERE target.ProvinceCode=source.ProvinceCode);
UPDATE dbo.AdministrativeProvinces SET IsActive=0
WHERE NOT EXISTS (SELECT 1 FROM #ProvinceSource source WHERE source.ProvinceCode=dbo.AdministrativeProvinces.ProvinceCode);""",
        values_inserts("#WardSource", ("WardCode", "ProvinceCode", "WardName", "WardType", "EffectiveFrom"), ward_rows),
        """UPDATE target SET ProvinceCode=source.ProvinceCode, WardName=source.WardName, WardType=source.WardType,
    EffectiveFrom=source.EffectiveFrom, IsActive=1
FROM dbo.AdministrativeWards target INNER JOIN #WardSource source ON source.WardCode=target.WardCode;
INSERT dbo.AdministrativeWards (WardCode, ProvinceCode, WardName, WardType, EffectiveFrom)
SELECT source.WardCode, source.ProvinceCode, source.WardName, source.WardType, source.EffectiveFrom FROM #WardSource source
WHERE NOT EXISTS (SELECT 1 FROM dbo.AdministrativeWards target WHERE target.WardCode=source.WardCode);
UPDATE dbo.AdministrativeWards SET IsActive=0
WHERE NOT EXISTS (SELECT 1 FROM #WardSource source WHERE source.WardCode=dbo.AdministrativeWards.WardCode);
DROP TABLE #WardSource;
DROP TABLE #ProvinceSource;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
SELECT (SELECT COUNT(*) FROM dbo.AdministrativeProvinces WHERE IsActive=1) AS ActiveProvinces,
       (SELECT COUNT(*) FROM dbo.AdministrativeWards WHERE IsActive=1) AS ActiveWards;""",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n\n".join(sql) + "\n", encoding="utf-8-sig")
    print(f"Generated {output_path}: {len(province_rows)} provinces, {len(ward_rows)} communes")


if __name__ == "__main__":
    main()
