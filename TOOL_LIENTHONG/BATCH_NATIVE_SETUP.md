# Liên thông batch native

Ứng dụng mở một màn hình WinForms native. Chọn **Liên thông nhiều hồ sơ (mới)** để lọc theo đơn vị/đợt khám, kiểm tra điều kiện, chọn chứng thư Windows và ký/gửi tuần tự từng hồ sơ. **Giao diện liên thông cũ** vẫn có thể mở riêng trong WebView2; màn hình batch không dùng WebView2.

Mỗi lần chạy tạo một `LienThongBatch` và một `LienThongBatchItem` cho từng lần khám. API chỉ lưu hash SHA-256 của XML, thời điểm ký/gửi, message ID, mã giao dịch, trạng thái/lỗi và response (tối đa 200 KB); XML, chữ ký Base64 và JSON envelope không được ghi vào database. Thay đổi dữ liệu sau khi tạo XML yêu cầu tạo/ký XML mới. Timeout khi gửi được đánh dấu `Uncertain`; cần đối soát với cổng trước khi gửi lại.

## Cấu hình server

1. Từ thư mục dự án, chạy `KSK_API\.venv\Scripts\python.exe KSK_API\tools\deploy_lienthong_batch.py` để áp migration `deploy_lienthong_batch.sql` lên database `PKNK_KSK` (hoặc chạy SQL migration bằng SSMS).
2. Trong `KSK_API/.env`, đặt `KSK_BATCH_API_KEY` thành một chuỗi ngẫu nhiên dài và đặt `LIEN_THONG_BATCH_RETENTION_DAYS` theo chính sách lưu trữ của đơn vị (mặc định 90 ngày).
3. Khởi động lại FastAPI để nạp cấu hình.

API sẽ xóa batch đã quá hạn khi khởi động, tối đa mỗi 24 giờ và trước khi truy vấn nhật ký. Các endpoint đọc/ghi nhật ký batch yêu cầu header API key.

Có thể sinh khóa bằng `KSK_API\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"`. Không đưa khóa đó vào mã nguồn hoặc gửi qua chat; nhập vào `.env` trực tiếp trên server và vào ô cấu hình desktop tại máy ký.

## Cấu hình desktop

Mở **Cấu hình API**, nhập cùng `KSK_BATCH_API_KEY` trong ô **Batch API key**, rồi lưu. Ứng dụng mã hóa khóa bằng Windows DPAPI cho tài khoản Windows hiện tại trong `ini.txt`. Không sao chép chuỗi đã mã hóa sang tài khoản Windows khác; nhập lại khóa trên từng máy ký.

USB Token/private key và PIN không được ghi vào database hay file cấu hình. Chứng thư được dùng tuần tự qua Windows CSP/KSP. Chưa có thử ký/gửi thực tế nếu máy chưa cắm Token và chưa được chủ đơn vị phê duyệt việc gửi dữ liệu thật.
