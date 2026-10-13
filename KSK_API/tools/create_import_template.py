"""Create the blank XLSX template accepted by the administrative import page."""

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


OUTPUT = Path(__file__).resolve().parents[2] / "Mau_Excel_ThongTinHanhChinh_LienThong_KSK.xlsx"
HEADERS = [
    "SHS", "Họ và tên", "Giới tính (1=Nam, 2=Nữ)", "Ngày sinh", "Điện thoại",
    "CCCD/Hộ chiếu/Mã định danh", "Ngày cấp CCCD", "Nơi cấp CCCD", "Mã dân tộc",
    "Dân tộc", "Nhóm máu", "Tỉnh/Thành", "Mã tỉnh (3 ký tự)", "Phường/Xã",
    "Mã xã (5 ký tự)", "Số nhà/Thôn/Xóm", "Mã nghề nghiệp (2 ký tự)",
    "Nghề nghiệp", "Nơi làm việc, học tập",
]
GUIDE = [
    ("Mục", "Hướng dẫn nhập", "Trường XML liên quan"),
    ("Bắt đầu nhập", "Nhập dữ liệu từ dòng 2; giữ nguyên tên tiêu đề để import.html tự nhận diện cột. Không có dòng dữ liệu ví dụ để tránh nhập nhầm hồ sơ mẫu.", ""),
    ("Đơn vị / đợt khám", "Khi import, chọn Đơn vị và Đợt khám trên trang import.html. MST lấy từ đơn vị đã chọn, không nhập trong file.", ""),
    ("SHS", "Số hồ sơ nội bộ của bệnh nhân; có thể để trống nếu đơn vị chưa cấp.", "Mã nội bộ, không phải trường XML hành chính."),
    ("Họ và tên", "Bắt buộc. Nhập đầy đủ họ tên có dấu.", "HO_TEN"),
    ("Giới tính", "Nhập 1 = Nam hoặc 2 = Nữ. Cột có danh sách chọn.", "GIOI_TINH"),
    ("Ngày sinh / Ngày cấp CCCD", "Nhập kiểu ngày trong Excel (dd/mm/yyyy). Hệ thống chuyển sang yyyyMMdd khi tạo XML.", "NGAY_SINH / NGAYCAP_CCCD"),
    ("Dân tộc", "Điền mã danh mục vào cột Mã dân tộc (giữ số 0 đầu, ví dụ 01) và tên hiển thị vào cột Dân tộc.", "MA_DAN_TOC"),
    ("Tỉnh/Thành, Phường/Xã", "Điền cả tên và mã hành chính hiện hành: mã tỉnh 3 ký tự, mã xã 5 ký tự. API kiểm tra xã thuộc tỉnh đã chọn.", "MATINH_CU_TRU / MAXA_CU_TRU"),
    ("Nghề nghiệp", "Điền mã nghề nghiệp vào cột mã và tên hiển thị vào cột nghề nghiệp; giữ số 0 đầu nếu có.", "MA_NGHE_NGHIEP"),
    ("Địa chỉ", "Địa chỉ XML được ghép từ Số nhà/Thôn/Xóm + Phường/Xã + Tỉnh/Thành.", "DIA_CHI"),
    ("Điện thoại / Nhóm máu / Nơi làm việc", "Điền nếu có; giữ CCCD và số điện thoại ở dạng văn bản để không mất số 0 đầu.", "DIEN_THOAI / NHOM_MAU / NOI_LAM_VIEC_HOC_TAP"),
    ("Lý do khám sức khỏe", "Không nhập trong file import bệnh nhân; lưu tại trường Lý do khám của form ksk-tu-du-18.html theo từng bệnh nhân và đợt khám.", "LY_DO_VV"),
]


def column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell(reference: str, value: str, style: int = 0) -> str:
    return (f'<c r="{reference}" t="inlineStr" s="{style}"><is>'
            f'<t xml:space="preserve">{escape(value)}</t></is></c>')


def worksheet(headers: list[str], widths: list[int]) -> str:
    col_parts = []
    for i, width in enumerate(widths, 1):
        style = ' style="2"' if i in (4, 7) else ""
        col_parts.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"{style}/>')
    cols = "".join(col_parts)
    row = "".join(cell(f"{column_name(i)}1", value, 1) for i, value in enumerate(headers, 1))
    last = column_name(len(headers))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{last}1"/><sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            f'</sheetView></sheetViews><cols>{cols}</cols><sheetData><row r="1" ht="40" customHeight="1">'
            f'{row}</row></sheetData><autoFilter ref="A1:{last}1000"/>'
            '<dataValidations count="1"><dataValidation type="list" allowBlank="1" '
            'showErrorMessage="1" sqref="C2:C1000"><formula1>"1,2"</formula1>'
            '</dataValidation></dataValidations></worksheet>')


def guide_sheet() -> str:
    rows = []
    for row_index, values in enumerate(GUIDE, 1):
        cells = "".join(cell(f"{column_name(col)}{row_index}", value, 1 if row_index == 1 else 0)
                        for col, value in enumerate(values, 1))
        rows.append(f'<row r="{row_index}">{cells}</row>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:C{len(GUIDE)}"/><sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews><cols><col min="1" max="1" width="27" customWidth="1"/>'
            '<col min="2" max="2" width="105" customWidth="1"/>'
            '<col min="3" max="3" width="43" customWidth="1"/></cols>'
            f'<sheetData>{"".join(rows)}</sheetData><autoFilter ref="A1:C{len(GUIDE)}"/>'
            '</worksheet>')


PARTS = {
    "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''',
    "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''',
    "xl/workbook.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView xWindow="0" yWindow="0" windowWidth="20000" windowHeight="12000"/></bookViews><sheets><sheet name="ThongTinHanhChinh" sheetId="1" r:id="rId1"/><sheet name="HuongDan" sheetId="2" r:id="rId2"/></sheets><calcPr calcId="191029"/></workbook>''',
    "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''',
    "xl/styles.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="0"/><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF147D50"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FFD9E2DC"/></bottom><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" horizontal="center" wrapText="1"/></xf><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''',
}


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    parts = dict(PARTS)
    parts["xl/worksheets/sheet1.xml"] = worksheet(HEADERS, [16, 28, 22, 15, 17, 27, 16, 23, 15, 18, 14, 22, 18, 22, 18, 25, 22, 30, 28])
    parts["xl/worksheets/sheet2.xml"] = guide_sheet()
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode("utf-8"))
    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
