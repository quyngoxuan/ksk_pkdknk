"""Create a blank Excel workbook for KSK exam sections 2–6.

This is a data-entry template only. The current import.html workflow imports
administrative patient data; it does not yet import these exam sheets.
"""

from pathlib import Path
import argparse
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


OUTPUT = Path(__file__).resolve().parents[2] / "Mau_Excel_ThongTinKSK_Muc2-6.xlsx"

HISTORY = [
    "Có bệnh hay bị thương trong 5 năm qua",
    "Có bệnh thần kinh hay bị thương ở đầu",
    "Bệnh mắt hoặc giảm thị lực (trừ trường hợp đeo kính thuốc)",
    "Bệnh ở tai, giảm sức nghe hoặc thăng bằng",
    "Bệnh ở tim hoặc nhồi máu cơ tim, các bệnh tim mạch khác",
    "Phẫu thuật can thiệp tim - mạch",
    "Tăng huyết áp",
    "Khó thở",
    "Bệnh phổi, hen, khí quản thủng, viêm phế quản mạn tính",
    "Bệnh thận, lọc máu",
    "Nghiện rượu, bia",
    "Đái tháo đường hoặc kiểm soát tăng đường huyết",
    "Bệnh tâm thần",
    "Mất ý thức, rối loạn ý thức",
    "Ngất, chóng mặt",
    "Bệnh tiêu hóa",
    "Rối loạn giấc ngủ, ngừng thở khi ngủ, ngủ rũ ban ngày, ngáy to",
    "Tai biến mạch máu não hoặc liệt",
    "Bệnh hoặc tổn thương cột sống",
    "Sử dụng rượu thường xuyên, liên tục",
    "Sử dụng ma túy, chất gây nghiện",
    "Bệnh khác (ghi rõ)",
]

CLINICAL = [
    ("INTERNAL_CIRCULATION", "Nội khoa — Tuần hoàn"),
    ("INTERNAL_RESPIRATORY", "Nội khoa — Hô hấp"),
    ("INTERNAL_DIGESTIVE", "Nội khoa — Tiêu hóa"),
    ("INTERNAL_UROGENITAL", "Nội khoa — Thận-Tiết niệu-Sinh dục"),
    ("INTERNAL_ENDOCRINE", "Nội khoa — Nội tiết"),
    ("INTERNAL_MUSCULOSKELETAL", "Nội khoa — Cơ-Xương-Khớp"),
    ("INTERNAL_NEUROLOGY", "Nội khoa — Thần kinh"),
    ("INTERNAL_PSYCHIATRY", "Nội khoa — Tâm thần"),
    ("SURGERY", "Ngoại khoa"),
    ("DERMATOLOGY", "Da liễu"),
    ("OBSTETRICS", "Sản phụ khoa"),
    ("EYE", "Mắt"),
    ("ENT", "Tai-Mũi-Họng"),
    ("DENTAL", "Răng-Hàm-Mặt"),
]

KEYS = ["SHS", "MST", "CampaignId"]


def col_name(index: int) -> str:
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def cell(ref: str, value: object, style: int = 0) -> str:
    text = escape(str(value), {'"': "&quot;"})
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def worksheet(rows: list[list[object]], widths: list[int], filtered: bool = True) -> str:
    last_col = col_name(max((len(row) for row in rows), default=1))
    last_row = max(len(rows), 1)
    cols = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
    body = []
    for row_no, row in enumerate(rows, 1):
        style = 1 if row_no == 1 else 0
        cells = "".join(cell(f"{col_name(i)}{row_no}", value, style) for i, value in enumerate(row, 1))
        body.append(f'<row r="{row_no}">{cells}</row>')
    autofilter = f'<autoFilter ref="A1:{last_col}{last_row}"/>' if filtered and last_row > 1 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>{autofilter}</worksheet>'
    )


def common_header(*fields: str) -> list[str]:
    return [*KEYS, *fields]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Output .xlsx path")
    output_path = parser.parse_args().output.resolve()
    sheets: list[tuple[str, list[list[object]], list[int]]] = []
    guide = [
        ["HƯỚNG DẪN — TEMPLATE NHẬP KẾT QUẢ KHÁM SỨC KHỎE MỤC 2–6", ""],
        ["Phạm vi", "Workbook gồm các sheet mục 2, 3, 4, 5, 6; nhập mỗi bệnh nhân/lần khám trên một dòng ở từng sheet cần dùng."],
        ["Khóa hồ sơ", "SHS + MST + CampaignId phải trùng nhau trên tất cả các sheet để nhận diện đúng bệnh nhân và đợt khám."],
        ["Định dạng", "Giữ nguyên hàng tiêu đề và tên cột. Bắt đầu nhập từ dòng 2. Không thêm dấu nháy đơn vào đầu dữ liệu trừ khi cần giữ số 0 đầu."],
        ["Mục 2 — tiền sử", "Các cột H01–H22 nhập 1 = Có, 0 = Không, để trống = chưa khai báo. Tiền sử gia đình: 1 = Có, 0 = Không."],
        ["Mục 3 — thể lực", "Nhập chiều cao cm, cân nặng kg, mạch lần/phút, huyết áp và phân loại thể lực. BMI/phân loại BMI được form tính tự động; không nhập ở đây."],
        ["Mục 4 — lâm sàng", "Mỗi chuyên khoa có mã trường, kết quả/chi tiết và tên bác sĩ. Các trường mắt, tai-mũi-họng, răng-hàm-mặt theo các cột riêng."],
        ["Mục 5 — cận lâm sàng", "Nhập kết quả xét nghiệm/hình ảnh vào cột tương ứng. Có thể ghi nhiều chỉ số trong một ô, kèm đơn vị và khoảng tham chiếu."],
        ["Mục 6 — kết luận", "Phân loại sức khỏe: 1=Loại I, 2=Loại II, 3=Loại III, 4=Loại IV, 5=Loại V. Ngày kết luận dùng định dạng ngày Excel hoặc yyyy-mm-dd."],
        ["Lưu ý quan trọng", "Đây hiện là file mẫu để chuẩn hóa nhập liệu. Chức năng import.html hiện chưa đọc các sheet mục 2–6; không tải workbook này lên import.html để nhập."],
        ["An toàn dữ liệu", "Không điền dữ liệu bệnh nhân thật vào bản mẫu dùng chung. Hạn chế gửi file có thông tin sức khỏe qua kênh không bảo mật."],
    ]
    sheets.append(("HuongDan", guide, [26, 115]))

    history_headers = common_header(
        "Tiền sử gia đình — có người mắc bệnh (1=Có, 0=Không)",
        "Tiền sử gia đình — bệnh cụ thể",
        *[f"H{i:02d} — {label} (1=Có, 0=Không)" for i, label in enumerate(HISTORY, 1)],
        "Đang điều trị bệnh gì?", "Tiền sử thai sản (nếu có)",
    )
    sheets.append(("Muc2_TienSu", [history_headers], [14, 16, 14, 38, 38, *([34] * len(HISTORY)), 38, 38]))

    physical_headers = common_header(
        "Chiều cao (cm)", "Cân nặng (kg)", "Mạch (lần/phút)", "Huyết áp (mmHg)", "Phân loại thể lực", "Ghi chú"
    )
    sheets.append(("Muc3_TheLuc", [physical_headers], [14, 16, 16, 16, 18, 20, 40, 40, 40]))

    clinical_headers = common_header(*[x for code, label in CLINICAL for x in (f"{code} — {label}: Kết quả/chi tiết", f"{code} — Bác sĩ")],
                                     "Thị lực không kính (MP/MT)", "Thị lực có kính (MP/MT)", "Bệnh về mắt",
                                     "Thính lực tai phải", "Thính lực tai trái", "Bệnh Tai-Mũi-Họng",
                                     "Răng-Hàm-Mặt — Hàm trên", "Răng-Hàm-Mặt — Hàm dưới", "Bệnh Răng-Hàm-Mặt")
    sheets.append(("Muc4_LamSang", [clinical_headers], [14, 16, 14, *([34, 24] * len(CLINICAL)), 24, 24, 32, 22, 22, 32, 24, 24, 32]))

    lab = [
        ("HEMATOLOGY", "Huyết học — Tổng phân tích tế bào máu ngoại vi"),
        ("BLOOD_BIOCHEMISTRY", "Sinh hóa máu"),
        ("URINALYSIS", "Tổng phân tích nước tiểu"),
        ("URINE_OTHER", "Xét nghiệm nước tiểu khác"),
        ("CHEST_XRAY", "X-quang tim phổi thẳng"),
        ("OTHER_PARACLINICAL", "Cận lâm sàng khác"),
        ("PERIODIC_PARACLINICAL", "Cận lâm sàng định kỳ theo chỉ định"),
    ]
    lab_headers = common_header(*[f"{code} — {label}" for code, label in lab])
    sheets.append(("Muc5_CanLamSang", [lab_headers], [14, 16, 14, *([48] * len(lab))]))

    conclusion_headers = common_header("Tình trạng sức khỏe; bệnh, tật", "Phân loại sức khỏe (1–5)", "Ngày kết luận",
                                       "Người kết luận", "Chức danh / ghi chú", "Mã bệnh (nếu có)")
    sheets.append(("Muc6_KetLuan", [conclusion_headers], [14, 16, 14, 55, 20, 18, 28, 38, 24]))

    # One-row alternative containing every input field from sections 2–6.
    all_fields = [
        "Tiền sử gia đình — có người mắc bệnh (1=Có, 0=Không)",
        "Tiền sử gia đình — bệnh cụ thể",
        *[f"H{i:02d} — {label} (1=Có, 0=Không)" for i, label in enumerate(HISTORY, 1)],
        "Đang điều trị bệnh gì?", "Tiền sử thai sản (nếu có)",
        "Chiều cao (cm)", "Cân nặng (kg)", "Mạch (lần/phút)", "Huyết áp (mmHg)", "Phân loại thể lực", "Ghi chú thể lực",
        *[x for code, label in CLINICAL for x in (f"{code} — {label}: Kết quả/chi tiết", f"{code} — Bác sĩ")],
        "Thị lực không kính (MP/MT)", "Thị lực có kính (MP/MT)", "Bệnh về mắt",
        "Thính lực tai phải", "Thính lực tai trái", "Bệnh Tai-Mũi-Họng",
        "Răng-Hàm-Mặt — Hàm trên", "Răng-Hàm-Mặt — Hàm dưới", "Bệnh Răng-Hàm-Mặt",
        *[f"{code} — {label}" for code, label in lab],
        "Tình trạng sức khỏe; bệnh, tật", "Phân loại sức khỏe (1–5)", "Ngày kết luận",
        "Người kết luận", "Chức danh / ghi chú kết luận", "Mã bệnh (nếu có)",
    ]
    all_widths = [14, 16, 14] + [32] * len(all_fields)
    sheets.append(("TatCa_Muc2-6", [common_header(*all_fields)], all_widths))

    content_types = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                     '<Default Extension="xml" ContentType="application/xml"/>',
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    content_types.extend(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
    workbook_sheets = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _, _) in enumerate(sheets, 1))
    rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    rels += f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'

    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + "".join(content_types) + "</Types>")
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + workbook_sheets + '</sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels + '</Relationships>')
        zf.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF176B4D"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs></styleSheet>')
        for i, (_, rows, widths) in enumerate(sheets, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", worksheet(rows, widths, filtered=i > 1))

    print(f"Created {output_path}")


if __name__ == "__main__":
    main()
