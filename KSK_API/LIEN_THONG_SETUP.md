# Cấu hình liên thông HSSK Hà Nội

Thiết lập này tuân theo Phụ lục II của tài liệu `20072026 lien thong du lieu CS KCB lên hsskđt.pdf`.

1. Đăng ký tài khoản liên thông và dải IP gửi dữ liệu với Sở Y tế Hà Nội. Tài liệu yêu cầu IP máy gửi phải được whitelist.
2. Trong `KSK_API/.env`, khai báo `LIEN_THONG_USERNAME`, `LIEN_THONG_PASSWORD`, `LIEN_THONG_SENDER_ID`. Các giá trị mặc định đã dùng là `LIEN_THONG_BASE_URL=https://api-hssk.hanoi.gov.vn`, `LIEN_THONG_RECEIVER_ID=VTS`, `LIEN_THONG_VERSION=1.0`.
3. Khởi động lại API, rồi mở `http://localhost:5500/lienthong.html` và bấm **Kiểm tra đăng nhập HSSK Hà Nội**.
4. Dán XML khám sức khỏe theo cấu trúc Quyết định 2062/QĐ-BYT. XML phải có đầy đủ họ tên, ngày sinh, giới tính, mã tỉnh cư trú, mã xã cư trú và CCCD/mã định danh.
5. Dán chữ ký Base64 tạo theo quy trình ký số được đơn vị cấp tài khoản hướng dẫn. PDF yêu cầu chữ ký số nhưng không nêu thuật toán hoặc quy tắc tạo chữ ký, nên API không tự ký bằng private key.
6. Bấm **Tạo preview payload**, kiểm tra `header`, `data.content` và `signature`, sau đó mới bấm đẩy. Lưu `maGiaoDich` từ phản hồi để tra cứu tại `https://hssk.hanoi.gov.vn`.

Không lưu mật khẩu, access token hoặc chữ ký số vào HTML hay Git.

## Chọn chứng thư số / USB Token

Tài liệu Viettel xác nhận luồng nghiệp vụ: chọn hồ sơ, bấm đồng bộ, xác nhận phương pháp ký số và chọn chứng thư số/USB Token. Tuy nhiên tài liệu không công bố cổng cục bộ, thuật toán hoặc API của phần mềm ký số. Vì vậy `lienthong.html` không tự truy cập private key, không yêu cầu mã PIN và không giả định một cổng của Viettel/V20.

Khi đơn vị vận hành đã cài **Local Signer Bridge** trên máy trạm và xác nhận giao thức, chọn **Chọn chứng thư số / USB Token**, nhập địa chỉ loopback của bridge (ví dụ `http://127.0.0.1:18181`), rồi bấm nút chọn chứng thư. Giao diện sử dụng hợp đồng bộ điều hợp sau:

1. `GET {bridge}/certificates` trả về mảng chứng thư, hoặc `{ "certificates": [...] }` / `{ "data": [...] }`. Mỗi phần tử cần một định danh (`id`, `certificate_id`, `certificateId`, `thumbprint` hoặc `serial_number`) và nên có `subject`, `issuer`, `valid_to`.
2. `POST {bridge}/sign` nhận JSON gồm `certificate_id`, `content` (XML UTF-8), `content_encoding: "utf-8"`, `purpose: "hssk-kham-suc-khoe"`; trả về `{ "signature": "<chu-ky-base64>" }` hoặc `{ "data": { "signature": "<chu-ky-base64>" } }`.
3. Bridge phải cho phép CORS từ `http://localhost:5500` (hoặc origin đang mở trang) và tự hiện hộp thoại chọn chứng thư/nhập PIN. Mã PIN chỉ được nhập trong công cụ ký số chính thức.

Nếu Viettel/V20 cung cấp giao thức khác, cần điều chỉnh bộ điều hợp theo tài liệu kỹ thuật chính thức của họ trước khi sử dụng để ký thật. Có thể tạm dùng lựa chọn **Đã có chữ ký Base64** để dán chữ ký được tạo bởi công cụ ký số đã được phê duyệt.

## USB Token NC-CA qua Local Signer Bridge

Khi dùng USB Token NC-CA, chạy [KSK_LocalSignerBridge](../KSK_LocalSignerBridge/README.md) trên **máy đang cắm Token**, sau khi cài đúng driver/Token Manager NC-CA. Bridge chỉ mở `http://127.0.0.1:18181`, đọc chứng thư RSA từ `CurrentUser\My` và gọi Windows CSP/CNG ký RSA-SHA256; mã PIN và private key không đi qua HTML, API KSK hay SQL Server.

Trong `lienthong.html`, chọn **Chọn chứng thư số / USB Token**. Địa chỉ mặc định là `http://127.0.0.1:18181`; bấm nút chọn chứng thư, chọn chứng thư cần dùng rồi bấm **Ký XML bằng USB Token**. Khi Token Manager/CSP yêu cầu, nhập PIN tại cửa sổ của nó.

Bridge nhận XML UTF-8 và trả về `signature` Base64. Trước khi đẩy dữ liệu thật, cần đầu mối HSSK xác nhận nội dung cần ký cho trường `signature`; tài liệu API hiện có chưa nêu rõ là XML gốc, `data.content` Base64 hay JSON chuẩn hóa.

## Bổ sung dữ liệu chuẩn QĐ 2062

1. Chạy migration [deploy_ksk_lienthong_2062.sql](../deploy_ksk_lienthong_2062.sql) trên database `PKNK_KSK` bằng SSMS với tài khoản có quyền `ALTER` và `CREATE TABLE`.
2. Khai báo cơ sở KCB gồm `MA_CSKCB` (5 chữ số) và `MA_GTIN_CSKCB` (13 chữ số) qua Swagger: `POST /api/v1/lien-thong/facilities`.
3. Gán `facility_id`, `exam_type_code`, `subject_codes`, `payment_source_code` cho mỗi lần khám qua `PATCH /api/v1/exams/{exam_id}`. Cập nhật mã dân tộc/tỉnh/xã/nghề nghiệp cho bệnh nhân qua `PATCH /api/v1/patients/{patient_id}`.
4. Lưu các tag XML đặc thù, đặc biệt `CKS_NGUOI_KET_LUAN` và `CKS_BENH_VIEN`, qua `PUT /api/v1/exams/{exam_id}/lien-thong/fields`.
5. Trước khi sinh XML, gọi `GET /api/v1/exams/{exam_id}/lien-thong/readiness`. Chỉ được gửi khi `ready` là `true`; các phần tử trong `errors` là điều kiện bắt buộc còn thiếu, còn `warnings` cần được rà soát chuyên môn.
