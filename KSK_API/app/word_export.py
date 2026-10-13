"""Fill the administrative part of the supplied KSK Word template.

This module intentionally uses only the Python standard library.  It edits a
copy of the .docx package, so the original Ministry template and its layout
remain the source document.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET
import struct
import zlib


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WORD_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PICTURE_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
NS = {"w": WORD_NS}
ET.register_namespace("w", WORD_NS)
ET.register_namespace("r", REL_NS)
ET.register_namespace("a", DRAWING_NS)
ET.register_namespace("wp", WORD_DRAWING_NS)
ET.register_namespace("pic", PICTURE_NS)

CODE39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
    "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn",
    "A": "wnnnnwnnw", "B": "nnwnnwnnw", "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn",
    "F": "nnwnwwnnn", "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww", "O": "wnnnwnnwn",
    "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn", "S": "nnwnnnwwn", "T": "nnnnwnwwn",
    "U": "wwnnnnnnw", "V": "nwwnnnnnw", "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn",
    "Z": "nwwnwnnnn", "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "$": "nwnwnwnnn",
    "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn", "*": "nwnnwnwnn",
}


def _text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.findall(".//w:t", NS))


def _set_text(paragraph: ET.Element, content: str) -> None:
    """Replace visible text while retaining the paragraph and first run style."""
    text_nodes = paragraph.findall(".//w:t", NS)
    if not text_nodes:
        run = ET.SubElement(paragraph, f"{{{WORD_NS}}}r")
        text_nodes = [ET.SubElement(run, f"{{{WORD_NS}}}t")]
    text_nodes[0].text = content
    if content.startswith(" ") or content.endswith(" "):
        text_nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for node in text_nodes[1:]:
        node.text = ""


def _as_text(value: object | None) -> str:
    return str(value).strip() if value is not None else ""


def _format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _age(value: date | None) -> str:
    if not value:
        return ""
    today = date.today()
    years = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    return str(max(years, 0))


def _replace_next_placeholder(paragraphs: list[ET.Element], starts_with: str, content: str) -> None:
    """Write in the dotted field immediately following a label, not the label."""
    for index, paragraph in enumerate(paragraphs):
        if not _text(paragraph).strip().startswith(starts_with):
            continue
        # In the supplied template label and dotted input cell are separate
        # Word paragraphs/table cells. Do not travel past the next field label.
        for candidate in paragraphs[index + 1:index + 8]:
            candidate_text = _text(candidate)
            if re.search(r"\.{3,}", candidate_text):
                _set_text(candidate, re.sub(r"\.{3,}", content, candidate_text, count=1))
                return
            if re.match(r"\s*\d+\.\s", candidate_text):
                return
        return


def _replace_dotted_values(paragraphs: list[ET.Element], starts_with: str, values: list[str]) -> None:
    """Fill one or more dotted fields contained in the same Word paragraph."""
    for paragraph in paragraphs:
        paragraph_text = _text(paragraph)
        if not paragraph_text.strip().startswith(starts_with):
            continue
        replacements = iter(values)
        filled = re.sub(r"\.{3,}", lambda match: next(replacements, match.group(0)), paragraph_text)
        _set_text(paragraph, filled)
        return


def _replace_same_line(paragraphs: list[ET.Element], starts_with: str, content: str) -> None:
    for paragraph in paragraphs:
        if _text(paragraph).strip().startswith(starts_with):
            _set_text(paragraph, f"{starts_with} {content}")
            return


def _mark_gender(paragraphs: list[ET.Element], gender: int | None) -> None:
    """Tick the existing Nam/Nữ checkbox symbols without moving the labels."""
    start = next((index for index, item in enumerate(paragraphs) if _text(item).strip().startswith("2. Giới tính")), None)
    if start is None:
        return
    is_male = gender == 1
    is_female = gender == 2
    seen_gender = 0
    for paragraph in paragraphs[start + 1:start + 7]:
        if _text(paragraph).strip() != "□":
            continue
        seen_gender += 1
        if (seen_gender == 1 and is_male) or (seen_gender == 2 and is_female):
            _set_text(paragraph, "☒")


def _png_from_code39(value: str, module: int = 2, height: int = 46) -> bytes:
    """Return a compact monochrome PNG containing a Code 39 barcode."""
    payload = f"*{value.upper()}*"
    if any(character not in CODE39 for character in payload):
        raise ValueError("Mã hồ sơ có ký tự không hỗ trợ bởi Code 39.")
    bars: list[bool] = [False] * 10
    for character in payload:
        pattern = CODE39[character]
        for index, width in enumerate(pattern):
            bars.extend([index % 2 == 0] * (3 if width == "w" else 1))
        bars.extend([False] * 1)  # Inter-character gap.
    bars.extend([False] * 10)
    width = len(bars) * module
    raw = bytearray()
    for _ in range(height):
        raw.append(0)  # PNG filter type.
        for black in bars:
            raw.extend((0 if black else 255,) * module)

    def chunk(kind: bytes, content: bytes) -> bytes:
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def _barcode_drawing(relationship_id: str, name: str, width_px: int, height_px: int) -> ET.Element:
    """Create inline DrawingML equivalent to inserting a small PNG in Word."""
    emu_per_pixel = 9525
    cx, cy = width_px * emu_per_pixel, height_px * emu_per_pixel
    run = ET.Element(f"{{{WORD_NS}}}r")
    drawing = ET.SubElement(run, f"{{{WORD_NS}}}drawing")
    inline = ET.SubElement(drawing, f"{{{WORD_DRAWING_NS}}}inline", {"distT": "0", "distB": "0", "distL": "114300", "distR": "0"})
    ET.SubElement(inline, f"{{{WORD_DRAWING_NS}}}extent", {"cx": str(cx), "cy": str(cy)})
    ET.SubElement(inline, f"{{{WORD_DRAWING_NS}}}docPr", {"id": "9876", "name": name, "descr": f"Barcode {name}"})
    graphic = ET.SubElement(inline, f"{{{DRAWING_NS}}}graphic")
    graphic_data = ET.SubElement(graphic, f"{{{DRAWING_NS}}}graphicData", {"uri": "http://schemas.openxmlformats.org/drawingml/2006/picture"})
    picture = ET.SubElement(graphic_data, f"{{{PICTURE_NS}}}pic")
    nv_pic_pr = ET.SubElement(picture, f"{{{PICTURE_NS}}}nvPicPr")
    ET.SubElement(nv_pic_pr, f"{{{PICTURE_NS}}}cNvPr", {"id": "0", "name": name})
    ET.SubElement(nv_pic_pr, f"{{{PICTURE_NS}}}cNvPicPr")
    blip_fill = ET.SubElement(picture, f"{{{PICTURE_NS}}}blipFill")
    ET.SubElement(blip_fill, f"{{{DRAWING_NS}}}blip", {f"{{{REL_NS}}}embed": relationship_id})
    stretch = ET.SubElement(blip_fill, f"{{{DRAWING_NS}}}stretch")
    ET.SubElement(stretch, f"{{{DRAWING_NS}}}fillRect")
    shape_properties = ET.SubElement(picture, f"{{{PICTURE_NS}}}spPr")
    transform = ET.SubElement(shape_properties, f"{{{DRAWING_NS}}}xfrm")
    ET.SubElement(transform, f"{{{DRAWING_NS}}}off", {"x": "0", "y": "0"})
    ET.SubElement(transform, f"{{{DRAWING_NS}}}ext", {"cx": str(cx), "cy": str(cy)})
    preset_geometry = ET.SubElement(shape_properties, f"{{{DRAWING_NS}}}prstGeom", {"prst": "rect"})
    ET.SubElement(preset_geometry, f"{{{DRAWING_NS}}}avLst")
    return run


def _append_barcode_to_shs(paragraphs: list[ET.Element], relationship_id: str, code: str, width_px: int) -> bool:
    for paragraph in paragraphs:
        if _text(paragraph).strip().startswith("SHS:"):
            paragraph.append(_barcode_drawing(relationship_id, code, min(width_px, 260), 34))
            return True
    return False


def _add_shs_barcode_line_when_missing(document: ET.Element, relationship_id: str, code: str, width_px: int, shs: str) -> None:
    body = document.find(f"{{{WORD_NS}}}body")
    if body is None:
        return
    # The A4 template places personal fields in a narrow table. Put the
    # SHS/barcode in the full-width body just above that table so barcode and
    # SHS stay together at the page header instead of wrapping inside a cell.
    for index, node in enumerate(list(body)):
        if node.tag != f"{{{WORD_NS}}}tbl" or "1. Họ và tên" not in _text(node):
            continue
        line = ET.Element(f"{{{WORD_NS}}}p")
        properties = ET.SubElement(line, f"{{{WORD_NS}}}pPr")
        ET.SubElement(properties, f"{{{WORD_NS}}}jc", {f"{{{WORD_NS}}}val": "right"})
        spacing = ET.SubElement(properties, f"{{{WORD_NS}}}spacing")
        spacing.set(f"{{{WORD_NS}}}before", "0")
        spacing.set(f"{{{WORD_NS}}}after", "0")
        run = ET.SubElement(line, f"{{{WORD_NS}}}r")
        text = ET.SubElement(run, f"{{{WORD_NS}}}t")
        text.text = f"SHS: {shs}    "
        line.append(_barcode_drawing(relationship_id, code, min(width_px, 190), 28))
        body.insert(index, line)
        return


def _add_barcode_relationship(relationships_xml: bytes) -> tuple[bytes, str]:
    relationships = ET.fromstring(relationships_xml)
    relationship_id = "rIdKskBarcode"
    ET.SubElement(relationships, f"{{{PACKAGE_REL_NS}}}Relationship", {
        "Id": relationship_id,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "Target": "media/mahs-barcode.png",
    })
    return ET.tostring(relationships, encoding="utf-8", xml_declaration=True), relationship_id


def _ensure_png_content_type(content_types_xml: bytes) -> bytes:
    content_types = ET.fromstring(content_types_xml)
    namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    if not any(item.get("Extension") == "png" for item in content_types.findall(f"{{{namespace}}}Default")):
        ET.SubElement(content_types, f"{{{namespace}}}Default", {"Extension": "png", "ContentType": "image/png"})
    return ET.tostring(content_types, encoding="utf-8", xml_declaration=True)


def _restore_ignorable_namespace_declarations(xml_bytes: bytes, source_xml: bytes) -> bytes:
    """Keep namespace declarations named by mc:Ignorable after ElementTree serialization.

    ElementTree drops unused xmlns declarations, but Word requires prefixes in
    the mc:Ignorable value to remain declared on the document root.
    """
    source_text = source_xml.decode("utf-8")
    source_root_match = re.search(r"<[^!?][^>]*>", source_text)
    output_text = xml_bytes.decode("utf-8")
    output_root_match = re.search(r"<[^!?][^>]*>", output_text)
    if source_root_match is None or output_root_match is None:
        return xml_bytes

    source_root = source_root_match.group(0)
    output_root = output_root_match.group(0)
    ignorable_match = re.search(r"\bIgnorable=['\"]([^'\"]*)['\"]", source_root)
    if ignorable_match is None:
        return xml_bytes

    source_namespaces = dict(re.findall(r"xmlns:([\w.-]+)=['\"]([^'\"]+)['\"]", source_root))
    declarations = []
    for prefix in ignorable_match.group(1).split():
        uri = source_namespaces.get(prefix)
        if uri and not re.search(rf"\bxmlns:{re.escape(prefix)}=", output_root):
            declarations.append(f' xmlns:{prefix}="{uri}"')
    if not declarations:
        return xml_bytes

    closing = "/>" if output_root.endswith("/>") else ">"
    updated_root = output_root[:-len(closing)] + "".join(declarations) + closing
    return (output_text[:output_root_match.start()] + updated_root + output_text[output_root_match.end():]).encode("utf-8")


def _set_width(element: ET.Element, width: int) -> None:
    width_node = element.find(f"{{{WORD_NS}}}tcPr/{{{WORD_NS}}}tcW")
    if width_node is None:
        properties = element.find(f"{{{WORD_NS}}}tcPr")
        if properties is None:
            properties = ET.Element(f"{{{WORD_NS}}}tcPr")
            element.insert(0, properties)
        width_node = ET.SubElement(properties, f"{{{WORD_NS}}}tcW")
    width_node.set(f"{{{WORD_NS}}}w", str(width))
    width_node.set(f"{{{WORD_NS}}}type", "dxa")


def _widen_personal_history_table(document: ET.Element) -> None:
    """Format the 11-row history table compactly so it stays on page one."""
    for table in document.findall(".//w:tbl", NS):
        first_row = table.find("w:tr", NS)
        if first_row is None:
            continue
        headers = ["".join(node.text or "" for node in cell.findall(".//w:t", NS)).strip() for cell in first_row.findall("w:tc", NS)]
        if headers.count("Tên bệnh, tật") != 2:
            continue
        # The form uses two four-column panels on one printable page.
        # Keep total width at 9,760 twips without overflowing the right edge.
        widths = [550, 3850, 500, 750, 550, 3200, 550, 750]
        table_properties = table.find(f"{{{WORD_NS}}}tblPr")
        if table_properties is not None:
            table_width = table_properties.find(f"{{{WORD_NS}}}tblW")
            if table_width is not None:
                table_width.set(f"{{{WORD_NS}}}w", str(sum(widths)))
                table_width.set(f"{{{WORD_NS}}}type", "dxa")
            indentation = table_properties.find(f"{{{WORD_NS}}}tblInd")
            if indentation is not None:
                indentation.set(f"{{{WORD_NS}}}w", "0")
                indentation.set(f"{{{WORD_NS}}}type", "dxa")
            layout = table_properties.find(f"{{{WORD_NS}}}tblLayout")
            if layout is None:
                layout = ET.SubElement(table_properties, f"{{{WORD_NS}}}tblLayout")
            layout.set(f"{{{WORD_NS}}}type", "fixed")
        grid = table.findall("w:tblGrid/w:gridCol", NS)
        for column, width in zip(grid, widths):
            column.set(f"{{{WORD_NS}}}w", str(width))
        for row in table.findall("w:tr", NS):
            row_properties = row.find(f"{{{WORD_NS}}}trPr")
            if row_properties is None:
                row_properties = ET.Element(f"{{{WORD_NS}}}trPr")
                row.insert(0, row_properties)
            if row_properties.find(f"{{{WORD_NS}}}cantSplit") is None:
                ET.SubElement(row_properties, f"{{{WORD_NS}}}cantSplit")
            for cell, width in zip(row.findall("w:tc", NS), widths):
                _set_width(cell, width)
                cell_properties = cell.find(f"{{{WORD_NS}}}tcPr")
                margins = cell_properties.find(f"{{{WORD_NS}}}tcMar") if cell_properties is not None else None
                if margins is None:
                    margins = ET.SubElement(cell_properties, f"{{{WORD_NS}}}tcMar")
                for side in ("top", "bottom"):
                    margin = margins.find(f"{{{WORD_NS}}}{side}")
                    if margin is None:
                        margin = ET.SubElement(margins, f"{{{WORD_NS}}}{side}")
                    margin.set(f"{{{WORD_NS}}}w", "0")
                    margin.set(f"{{{WORD_NS}}}type", "dxa")
                for paragraph in cell.findall(".//w:p", NS):
                    _set_paragraph_font_size([paragraph], "", 22)  # 11 pt
                    paragraph_properties = paragraph.find(f"{{{WORD_NS}}}pPr")
                    if paragraph_properties is None:
                        paragraph_properties = ET.Element(f"{{{WORD_NS}}}pPr")
                        paragraph.insert(0, paragraph_properties)
                    spacing = paragraph_properties.find(f"{{{WORD_NS}}}spacing")
                    if spacing is None:
                        spacing = ET.SubElement(paragraph_properties, f"{{{WORD_NS}}}spacing")
                    spacing.set(f"{{{WORD_NS}}}before", "0")
                    spacing.set(f"{{{WORD_NS}}}after", "0")
                    spacing.set(f"{{{WORD_NS}}}line", "260")  # 13 pt
                    spacing.set(f"{{{WORD_NS}}}lineRule", "exact")
            # Keep the final 'Bệnh khác (ghi rõ) ....................' on
            # one line. Otherwise Word can push only the dotted tail to the
            # top of the next page.
            for cell in row.findall("w:tc", NS):
                if "Bệnh khác (ghi rõ)" not in _text(cell):
                    continue
                properties = cell.find(f"{{{WORD_NS}}}tcPr")
                if properties is None:
                    properties = ET.Element(f"{{{WORD_NS}}}tcPr")
                    cell.insert(0, properties)
                ET.SubElement(properties, f"{{{WORD_NS}}}noWrap")
                for paragraph in cell.findall(".//w:p", NS):
                    paragraph_text = _text(paragraph)
                    if "Bệnh khác (ghi rõ)" in paragraph_text:
                        if not re.search(r"\.{3,}\s*$", paragraph_text):
                            _set_text(paragraph, f"{paragraph_text.rstrip()} ....................")
                    _set_paragraph_font_size([paragraph], "Bệnh khác (ghi rõ)", 18)  # 9 pt
        return


def _set_paragraph_font_size(paragraphs: list[ET.Element], starts_with: str, half_points: int) -> None:
    for paragraph in paragraphs:
        if not _text(paragraph).strip().lower().startswith(starts_with.lower()):
            continue
        for run in paragraph.findall(".//w:r", NS):
            properties = run.find(f"{{{WORD_NS}}}rPr")
            if properties is None:
                properties = ET.Element(f"{{{WORD_NS}}}rPr")
                run.insert(0, properties)
            size = properties.find(f"{{{WORD_NS}}}sz")
            if size is None:
                size = ET.SubElement(properties, f"{{{WORD_NS}}}sz")
            size.set(f"{{{WORD_NS}}}val", str(half_points))
            size_cs = properties.find(f"{{{WORD_NS}}}szCs")
            if size_cs is None:
                size_cs = ET.SubElement(properties, f"{{{WORD_NS}}}szCs")
            size_cs.set(f"{{{WORD_NS}}}val", str(half_points))
        return


def _page_break_before(paragraphs: list[ET.Element], starts_with: str) -> None:
    """Start a major subsequent section on a fresh Word page."""
    for paragraph in paragraphs:
        if not _text(paragraph).strip().startswith(starts_with):
            continue
        properties = paragraph.find(f"{{{WORD_NS}}}pPr")
        if properties is None:
            properties = ET.Element(f"{{{WORD_NS}}}pPr")
            paragraph.insert(0, properties)
        if properties.find(f"{{{WORD_NS}}}pageBreakBefore") is None:
            ET.SubElement(properties, f"{{{WORD_NS}}}pageBreakBefore")
        return


def _remove_dot_leader_below_history_table(document: ET.Element) -> None:
    """Remove the empty dotted leader paragraph placed below the history table."""
    body = document.find(f"{{{WORD_NS}}}body")
    if body is None:
        return
    nodes = list(body)
    for index, node in enumerate(nodes):
        if node.tag != f"{{{WORD_NS}}}tbl" or "Tên bệnh, tật" not in "".join(item.text or "" for item in node.iter(f"{{{WORD_NS}}}t")):
            continue
        for following in nodes[index + 1:index + 3]:
            if following.tag != f"{{{WORD_NS}}}p":
                continue
            leader_tab = following.find(f".//{{{WORD_NS}}}tab[@{{{WORD_NS}}}leader='dot']")
            run_tab = following.find(f".//{{{WORD_NS}}}r/{{{WORD_NS}}}tab")
            if leader_tab is not None and run_tab is not None:
                body.remove(following)
        return


def _append_labeled_paragraph(body: ET.Element, index: int, label: str, content: str, *, font_size_pt: int | None = None) -> None:
    paragraph = ET.Element(f"{{{WORD_NS}}}p")
    properties = ET.SubElement(paragraph, f"{{{WORD_NS}}}pPr")
    spacing = ET.SubElement(properties, f"{{{WORD_NS}}}spacing")
    spacing.set(f"{{{WORD_NS}}}before", "0")
    spacing.set(f"{{{WORD_NS}}}after", "0")

    label_run = ET.SubElement(paragraph, f"{{{WORD_NS}}}r")
    run_properties = ET.SubElement(label_run, f"{{{WORD_NS}}}rPr")
    ET.SubElement(run_properties, f"{{{WORD_NS}}}b")
    if font_size_pt:
        ET.SubElement(run_properties, f"{{{WORD_NS}}}sz", {f"{{{WORD_NS}}}val": str(font_size_pt * 2)})
    label_text = ET.SubElement(label_run, f"{{{WORD_NS}}}t")
    label_text.text = label

    value_run = ET.SubElement(paragraph, f"{{{WORD_NS}}}r")
    if font_size_pt:
        value_properties = ET.SubElement(value_run, f"{{{WORD_NS}}}rPr")
        ET.SubElement(value_properties, f"{{{WORD_NS}}}sz", {f"{{{WORD_NS}}}val": str(font_size_pt * 2)})
    value_text = ET.SubElement(value_run, f"{{{WORD_NS}}}t")
    value_text.text = content
    if content.startswith(" ") or content.endswith(" "):
        value_text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    body.insert(index, paragraph)


def _append_conclusion(document: ET.Element, exam) -> None:
    """Add the saved conclusion fields after item 13 at the end of the form."""
    body = document.find(f"{{{WORD_NS}}}body")
    if body is None:
        return
    section_properties = body.find(f"{{{WORD_NS}}}sectPr")
    index = list(body).index(section_properties) if section_properties is not None else len(body)
    classification = _as_text(exam.health_classification)
    classification_names = {
        "1": "Loại I – Rất khỏe",
        "2": "Loại II – Khỏe",
        "3": "Loại III – Trung bình",
        "4": "Loại IV – Yếu",
        "5": "Loại V – Rất yếu",
    }
    classification = classification_names.get(classification, classification)
    _append_labeled_paragraph(body, index, "Kết luận: ", _as_text(exam.health_status), font_size_pt=13)
    _append_labeled_paragraph(body, index + 1, "Phân loại sức khỏe: ", classification)
    _append_labeled_paragraph(body, index + 2, "Ngày kết luận: ", _format_date(exam.conclusion_date))


def create_administrative_docx(template_path: Path, output_path: Path, patient, exam, *, include_conclusion: bool = False) -> None:
    """Create one Word document populated with patient administration fields."""
    with ZipFile(template_path, "r") as source:
        document = ET.fromstring(source.read("word/document.xml"))
        paragraphs = document.findall(".//w:p", NS)

        full_name = _as_text(patient.full_name).upper()
        gender = "Nam" if patient.gender == 1 else "Nữ" if patient.gender == 2 else ""
        address = _as_text(patient.address_detail)
        province = _as_text(patient.province)
        ward = _as_text(patient.ward)
        ethnicity = _as_text(patient.ethnicity)
        occupation = _as_text(patient.occupation)
        reason = _as_text(exam.exam_reason)
        subject_type = _as_text(exam.subject_type)
        payment_source = _as_text(exam.payment_source)

        _replace_same_line(paragraphs, "SHS:", _as_text(patient.shs))
        _replace_next_placeholder(paragraphs, "1. Họ và tên", full_name)
        _mark_gender(paragraphs, patient.gender)
        _replace_next_placeholder(paragraphs, "Điện thoại:", _as_text(patient.phone))
        _replace_next_placeholder(paragraphs, "3. Ngày tháng năm sinh", _format_date(patient.date_of_birth))
        _replace_next_placeholder(paragraphs, "Tuổi:", _age(patient.date_of_birth))
        _replace_next_placeholder(paragraphs, "4. Số CCCD", _as_text(patient.identity_number))
        _replace_next_placeholder(paragraphs, "5. Cấp ngày", _format_date(patient.identity_issue_date))
        _replace_next_placeholder(paragraphs, "Nơi cấp:", _as_text(patient.identity_issue_place))
        _replace_next_placeholder(paragraphs, "6. Dân tộc", ethnicity)
        _replace_next_placeholder(paragraphs, "7. Đối tượng", subject_type)
        _replace_next_placeholder(paragraphs, "8. Nguồn chi trả", payment_source)
        _replace_next_placeholder(paragraphs, "9. Nhóm máu", _as_text(patient.blood_group))
        _replace_dotted_values(paragraphs, "10. Nơi ở hiện tại", [province, ward])
        _replace_dotted_values(paragraphs, "số nhà/thôn/xóm", [address])
        _replace_dotted_values(paragraphs, "11. Nghề nghiệp", [occupation])
        _replace_dotted_values(paragraphs, "12. Nơi làm việc", [_as_text(patient.workplace)])
        _replace_dotted_values(paragraphs, "13. Lý do khám", [reason])
        if include_conclusion:
            _append_conclusion(document, exam)
        _set_paragraph_font_size(paragraphs, "số nhà/thôn/xóm", 20)  # 10 pt
        _widen_personal_history_table(document)
        _remove_dot_leader_below_history_table(document)
        _page_break_before(paragraphs, "3. Câu hỏi khác (nếu có):")

        mahs = _as_text(exam.exam_code) or f"KSK-{exam.exam_id}"
        barcode_png = _png_from_code39(mahs)
        barcode_width = struct.unpack(">I", barcode_png[16:20])[0]
        relationships_xml, barcode_relationship_id = _add_barcode_relationship(source.read("word/_rels/document.xml.rels"))
        content_types_xml = _ensure_png_content_type(source.read("[Content_Types].xml"))
        if not _append_barcode_to_shs(paragraphs, barcode_relationship_id, mahs, barcode_width):
            _add_shs_barcode_line_when_missing(document, barcode_relationship_id, mahs, barcode_width, _as_text(patient.shs))
        xml_bytes = ET.tostring(document, encoding="utf-8", xml_declaration=True)
        xml_bytes = _restore_ignorable_namespace_declarations(xml_bytes, source.read("word/document.xml"))
        with ZipFile(output_path, "w", ZIP_DEFLATED) as destination:
            for entry in source.infolist():
                if entry.filename == "word/document.xml":
                    destination.writestr(entry, xml_bytes)
                elif entry.filename == "word/_rels/document.xml.rels":
                    destination.writestr(entry, relationships_xml)
                elif entry.filename == "[Content_Types].xml":
                    destination.writestr(entry, content_types_xml)
                else:
                    destination.writestr(entry, source.read(entry.filename))
            destination.writestr("word/media/mahs-barcode.png", barcode_png)


def create_campaign_administrative_docx(template_path: Path, output_path: Path, records: list[tuple[object, object]]) -> None:
    """Create one DOCX containing one A4 administrative form per patient."""
    if not records:
        raise ValueError("Đợt khám chưa có hồ sơ bệnh nhân để xuất.")

    with tempfile.TemporaryDirectory(prefix="ksk_campaign_docx_") as temp_dir:
        temp_path = Path(temp_dir)
        package_parts: dict[str, bytes] | None = None
        document: ET.Element | None = None
        body: ET.Element | None = None
        section_properties: ET.Element | None = None
        relationships: ET.Element | None = None
        source_document_xml = b""
        extra_parts: dict[str, bytes] = {}
        next_relationship_id = 2
        next_drawing_id = 1

        for index, (patient, exam) in enumerate(records, 1):
            generated_path = temp_path / "current.docx"
            create_administrative_docx(template_path, generated_path, patient, exam)
            with ZipFile(generated_path, "r") as generated:
                generated_parts = {entry.filename: generated.read(entry.filename) for entry in generated.infolist()}
            generated_path.unlink(missing_ok=True)

            generated_document_xml = generated_parts["word/document.xml"]
            generated_document = ET.fromstring(generated_document_xml)
            generated_body = generated_document.find(f"{{{WORD_NS}}}body")
            if generated_body is None:
                raise ValueError("File mẫu Word không có phần nội dung hợp lệ.")

            if index == 1:
                package_parts = generated_parts
                document = generated_document
                body = generated_body
                source_document_xml = generated_document_xml
                section_properties = body.find(f"{{{WORD_NS}}}sectPr")
                if section_properties is not None:
                    body.remove(section_properties)
                relationships = ET.fromstring(generated_parts["word/_rels/document.xml.rels"])
                existing_drawing_ids = [
                    int(element.get("id", "0"))
                    for element in body.iter(f"{{{WORD_DRAWING_NS}}}docPr")
                    if element.get("id", "").isdigit()
                ]
                next_drawing_id = max(existing_drawing_ids, default=0) + 1
                continue

            assert body is not None and relationships is not None
            generated_relationships = ET.fromstring(generated_parts["word/_rels/document.xml.rels"])
            relationships_by_id = {
                item.get("Id"): item
                for item in generated_relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
            }
            page_break = ET.Element(f"{{{WORD_NS}}}p")
            break_run = ET.SubElement(page_break, f"{{{WORD_NS}}}r")
            ET.SubElement(break_run, f"{{{WORD_NS}}}br", {f"{{{WORD_NS}}}type": "page"})
            body.append(page_break)

            for source_child in list(generated_body):
                if source_child.tag == f"{{{WORD_NS}}}sectPr":
                    continue
                child = ET.fromstring(ET.tostring(source_child, encoding="utf-8"))
                for element in child.iter():
                    embedded_id = element.get(f"{{{REL_NS}}}embed")
                    relationship = relationships_by_id.get(embedded_id)
                    if relationship is not None and relationship.get("Target", "").endswith("mahs-barcode.png"):
                        new_id = f"rIdKskBarcode{next_relationship_id}"
                        new_target = f"media/mahs-barcode-{next_relationship_id}.png"
                        cloned_relationship = ET.fromstring(ET.tostring(relationship, encoding="utf-8"))
                        cloned_relationship.set("Id", new_id)
                        cloned_relationship.set("Target", new_target)
                        relationships.append(cloned_relationship)
                        element.set(f"{{{REL_NS}}}embed", new_id)
                        source_media = f"word/{relationship.get('Target')}"
                        extra_parts[f"word/{new_target}"] = generated_parts[source_media]
                        next_relationship_id += 1
                    if element.tag == f"{{{WORD_DRAWING_NS}}}docPr":
                        element.set("id", str(next_drawing_id))
                        next_drawing_id += 1
                body.append(child)

        assert package_parts is not None and document is not None and body is not None and relationships is not None
        if section_properties is not None:
            body.append(section_properties)
        package_parts["word/document.xml"] = _restore_ignorable_namespace_declarations(
            ET.tostring(document, encoding="utf-8", xml_declaration=True),
            source_document_xml,
        )
        package_parts["word/_rels/document.xml.rels"] = ET.tostring(
            relationships, encoding="utf-8", xml_declaration=True
        )
        package_parts.update(extra_parts)

        with ZipFile(output_path, "w", ZIP_DEFLATED) as destination:
            for filename, contents in package_parts.items():
                destination.writestr(filename, contents)
