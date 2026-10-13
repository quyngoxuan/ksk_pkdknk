# ksk_pkdknk

Ứng dụng quản lý thông tin khám sức khỏe
Lấy các file đã chỉnh sửa trong ngày hôm nay
mà cần coppy lên máy triển khai. Nén lại thành 1 file zip nhé

TỔNG HỢP CÁC YÊU CẦU ĐÃ TRAO ĐỔI

1. Phiếu khám Word/A4 và bố cục

- Điều chỉnh mẫu Word/A4, mẫu có ảnh: bảng Tiền sử bản thân nằm gọn trang 1; giữ đúng độ rộng bảng/cột, tăng cỡ chữ và giãn dòng theo yêu cầu; bỏ dòng chấm dưới bảng.
- Thêm nút tải phiếu A4 và nút tải Word có ảnh; lấy thông tin như nút tải Word, có barcode MaHS và đặt barcode cạnh SHS ở đầu trang.
- Sửa lỗi file Word không mở được; chỉnh riêng bố cục bảng/cột khi xuất A4 và mẫu có ảnh.
- Thêm nút “Lưu và Tải phiếu A4” cạnh “Lưu kết luận”. Nút mới lưu kết luận trước rồi xuất bản A4 riêng có thêm Kết luận, Phân loại sức khỏe và Ngày kết luận; nút A4 thông thường giữ nguyên. Trong bản mới, bỏ tiền tố “14.” trước “Kết luận” và đặt dòng này cỡ chữ 13 pt.
- Hướng dẫn xác định/cập nhật các file cần triển khai và đóng gói ZIP.

2. Barcode và in ấn

- Thêm nút In Barcode ở từng hồ sơ; in MaHS, họ tên và ngày sinh theo nhãn 3 x 10 cm, bố trí sát và dễ đọc.
- Sửa mẫu barcode không thay đổi khi in; xử lý tình trạng bản xem trước đứng nhưng máy in Godex in xoay ngang.
- Chuyển yêu cầu từ mở hộp thoại in sang xuất PDF khi phù hợp.

3. Danh sách hồ sơ (list.html)

- Sắp xếp bộ lọc trên một hàng; đưa ô mở hồ sơ về góc phải; bỏ ảnh mô tả barcode và điều chỉnh vị trí nút xóa đợt khám.
- Phân biệt nút Lọc/Tải lại; ẩn nút tải lại nếu không cần. Sửa chức năng xóa hồ sơ, lỗi API 500 và thiếu bảng LienThongBatchItem; làm rõ xóa theo gói khám/đợt khám.
- Thêm SHS sau Ngày tạo, hiển thị họ tên chữ hoa, chỉnh độ rộng cột Họ và tên/Địa chỉ/# và thêm viền bảng.
- Thêm nút xuất Excel theo gói khám, cột SHS ở cuối; sắp xếp SHS tăng dần trong Excel, SHS trống/null ở cuối; trên danh sách hiển thị SHS lớn trước.
- Thêm nút quay lại danh sách theo MST và CampaignId từ form khám.
- Lọc theo tên/CCCD/điện thoại, đơn vị và đợt khám; điều tra lỗi JSON khi tải danh sách.

4. Form khám (ksk-tu-du-18.html)

- Khi mở form mới, focus vào ô quét QR CCCD; nếu SHS=0 cho chọn công ty/đợt khám, hiển thị trạng thái SHS chờ cấp và tự cấp số lớn nhất + 1 khi lưu hành chính.
- Với hồ sơ đã có PatientId, cho sửa SHS bằng ô số và kiểm tra trùng trước khi lưu.
- Thêm nút quay lại danh sách và nút tải A4 sau khi lưu thông tin hành chính.
- Tab 4: thêm thao tác điền nhanh “Bình thường” theo từng nội dung khám, bố trí icon cạnh tiêu đề; hỗ trợ tổng hợp các kết quả bất thường vào ô Tình trạng sức khỏe, nối bằng dấu chấm phẩy, chỉ lấy nội dung kết quả không kèm nhãn mục.
- Tab 5: thêm các trường kết quả Đường máu, Ure, Creatinin, ASAT (GOT), ALAT (GPT) cùng bảng sinh hóa nhỏ gọn; điều chỉnh khoảng trắng/bố cục các mục.
- Tab 5: có nút điền nhanh “Bình thường” cho huyết học, tổng phân tích nước tiểu, sinh hóa máu và XQ Tim Phổi; cho phép đưa kết quả các mục này vào thao tác tổng hợp kết luận.
- Tab 6: có icon tổng hợp kết quả khác “Bình thường” từ tab 4 và các mục cận lâm sàng đã nêu ở tab 5; bỏ nhãn, giữ nội dung kết quả.

5. Menu và trang chính

- Áp dụng thiết kế menu dạng link có icon; tạo menu.html dùng chung để các trang gọi đến, đổi “Bệnh Nhân” thành “Danh Sách Hồ Sơ” và “Form KSK” thành “thêm HS KSK”.
- Gắn link cố định cho mục thêm hồ sơ; áp dụng menu trên tất cả trang HTML; tinh gọn phần tiêu đề main.html và đề xuất/thay khu vực nội dung bằng thống kê bảng/biểu đồ.
- Bổ sung chức năng Danh sách HS đã liên thông và trạng thái hồ sơ sau khi liên thông.

6. API, triển khai và dữ liệu

- Tạo file BAT/ứng dụng EXE để khởi động hoặc dừng API, có thể thu nhỏ xuống khay hệ thống; hướng dẫn triển khai trên máy mới.
- Xử lý lỗi cổng 5500 đang được sử dụng; hướng dẫn chạy thêm một cổng trên cùng máy và lưu sang cơ sở dữ liệu riêng.
- Hỏi cách xóa toàn bộ dữ liệu một đơn vị, gồm gói khám và hồ sơ; hướng dẫn câu lệnh truy vấn danh sách hồ sơ theo đợt.
- Hỏi có thể dùng Node.js thay IIS để cấu hình triển khai/tải file Word hay không.

7. Tài liệu và hỗ trợ khác

- Soạn tài liệu DOCX hướng dẫn quy trình nhập liệu: tạo đơn vị, tạo gói, nhập hồ sơ, thêm hồ sơ mới và nhập danh sách Excel; kèm ảnh minh họa.
- Hỏi gợi ý máy in barcode tại Việt Nam và hướng dẫn cấu hình tải file trên máy triển khai.
