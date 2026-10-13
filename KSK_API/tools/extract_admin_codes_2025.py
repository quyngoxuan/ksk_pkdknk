"""Parse the official NSO Appendix I PDF and emit the administrative catalog JSON.

Source: https://www.nso.gov.vn/wp-content/uploads/2025/06/Danh-sach-va-ma-so-cac-don-vi-hanh-chinh-cap-xa.pdf
The generated catalog is effective 2025-07-01 under Decision 19/2025/QD-TTg.
"""

import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader


PROVINCES = {
    "01": "Thành phố Hà Nội", "04": "Tỉnh Cao Bằng", "08": "Tỉnh Tuyên Quang",
    "11": "Tỉnh Điện Biên", "12": "Tỉnh Lai Châu", "14": "Tỉnh Sơn La",
    "15": "Tỉnh Lào Cai", "19": "Tỉnh Thái Nguyên", "20": "Tỉnh Lạng Sơn",
    "22": "Tỉnh Quảng Ninh", "24": "Tỉnh Bắc Ninh", "25": "Tỉnh Phú Thọ",
    "31": "Thành phố Hải Phòng", "33": "Tỉnh Hưng Yên", "37": "Tỉnh Ninh Bình",
    "38": "Tỉnh Thanh Hóa", "40": "Tỉnh Nghệ An", "42": "Tỉnh Hà Tĩnh",
    "44": "Tỉnh Quảng Trị", "46": "Thành phố Huế", "48": "Thành phố Đà Nẵng",
    "51": "Tỉnh Quảng Ngãi", "52": "Tỉnh Gia Lai", "56": "Tỉnh Khánh Hòa",
    "66": "Tỉnh Đắk Lắk", "68": "Tỉnh Lâm Đồng", "75": "Tỉnh Đồng Nai",
    "79": "Thành phố Hồ Chí Minh", "80": "Tỉnh Tây Ninh", "82": "Tỉnh Đồng Tháp",
    "86": "Tỉnh Vĩnh Long", "91": "Tỉnh An Giang", "92": "Thành phố Cần Thơ",
    "96": "Tỉnh Cà Mau",
}
PROVINCE_CODES = {name.removeprefix("Tỉnh ").removeprefix("Thành phố "): code for code, name in PROVINCES.items()}
ROW = re.compile(r"^\s*(\d{1,4})\s+(\d{5})\s+(.+?)\s+(Tỉnh|Thành phố|Tp)\s+(.+?)\s*$")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: extract_admin_codes_2025.py <official-pdf> <output-json>")
    source, destination = map(Path, sys.argv[1:])
    rows: dict[str, dict[str, str]] = {}
    for page in PdfReader(source).pages:
        for line in (page.extract_text(extraction_mode="layout") or "").splitlines():
            match = ROW.match(line)
            if not match:
                continue
            _, ward_code, ward_full_name, province_prefix, province_tail = match.groups()
            province_tail = province_tail.strip()
            province_key = province_tail
            if province_prefix == "Tp":
                province_key = province_tail
            province_code = PROVINCE_CODES.get(province_key)
            if not province_code:
                raise ValueError(f"Unknown province in row: {line!r}")
            ward_match = re.match(r"^(Xã|Phường|Đặc khu)\s+(.+)$", ward_full_name.strip())
            if not ward_match:
                raise ValueError(f"Unknown commune type in row: {line!r}")
            ward_type, ward_name = ward_match.groups()
            if ward_code in rows:
                raise ValueError(f"Duplicate commune code: {ward_code}")
            rows[ward_code] = {
                "province_code": province_code,
                "ward_code": ward_code,
                "ward_name": f"{ward_type} {ward_name.strip()}",
                "ward_type": ward_type,
            }
    if len(rows) != 3321:
        raise ValueError(f"Expected 3321 official commune rows, parsed {len(rows)}")
    catalog = {
        "source": "Quyết định 19/2025/QĐ-TTg; Công văn 1027/CTK-CSCL ngày 25/06/2025",
        "effective_from": "2025-07-01",
        "provinces": [{"province_code": code, "province_name": name} for code, name in PROVINCES.items()],
        "wards": sorted(rows.values(), key=lambda row: (row["province_code"], row["ward_code"])),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(PROVINCES)} provinces and {len(rows)} communes to {destination}")


if __name__ == "__main__":
    main()
