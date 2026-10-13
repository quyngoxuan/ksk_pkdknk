# KSK API

Backend FastAPI cho biểu mẫu khám sức khỏe từ đủ 18 tuổi. API sử dụng trực tiếp các bảng đã tạo trong database `PKNK_KSK`.

## Khởi chạy

```powershell
cd C:\PKNK_KSK\KSK_API
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 5500
```

Đặt mật khẩu SQL Server trong `.env`, không đưa mật khẩu vào mã nguồn. Ứng dụng phục vụ cả HTML, API và Swagger tại cổng `5500`: Swagger UI `http://localhost:5500/docs`; OpenAPI JSON `http://localhost:5500/openapi.json`; trang nhập `http://localhost:5500/import.html`.

## Danh mục Tỉnh/Thành và Phường/Xã

Danh mục hiện hành theo [Quyết định 19/2025/QĐ-TTg](https://chinhphu.vn/?classid=1&docid=214409&orggroupid=3&pageid=27160) và phụ lục mã cấp xã của Cục Thống kê. Chạy `deploy_admin_catalog_2025.sql` trên database `PKNK_KSK` (SSMS), hoặc dùng tài khoản cấu hình trong `.env` chạy:

```powershell
cd C:\PKNK_KSK\KSK_API
.\.venv\Scripts\python.exe tools\deploy_admin_catalog.py
```

Migration idempotent; kiểm tra sau chạy phải trả 34 tỉnh/thành và 3.321 phường/xã. API cung cấp `GET /api/v1/administrative/provinces` và `GET /api/v1/administrative/provinces/{province_code}/wards`. Sau khi cập nhật code hoặc migration, khởi động lại API để nạp route mới.

## Nhóm API chính

- `GET /health`: kiểm tra API và kết nối cơ sở dữ liệu.
- `POST /api/v1/patients`, `GET /api/v1/patients`: tạo và tìm bệnh nhân.
- `POST /api/v1/exams`: tạo một lần khám, có thể kèm tiền sử, kết quả lâm sàng và cận lâm sàng.
- `GET /api/v1/exams/{exam_id}`: đọc toàn bộ hồ sơ của một lần khám.
- `PATCH /api/v1/exams/{exam_id}`: cập nhật thông tin chính, thể lực và kết luận.
- `PUT /api/v1/exams/{exam_id}/personal-histories`, `/clinical-results`, `/paraclinical-results`: thay thế danh sách kết quả chi tiết của lần khám.

Mỗi `HistoryCode`, `ExaminationCode` và `TestCode` phải là duy nhất trong một lần khám.
