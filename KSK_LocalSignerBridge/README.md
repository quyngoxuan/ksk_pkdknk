# NC-CA Local Signer Bridge

Bridge này chạy **trên chính máy đang cắm USB Token NC-CA**. Nó chỉ lắng nghe tại `127.0.0.1:18181`; không mở cổng ra mạng LAN/Internet.

Bridge đọc chứng thư từ Windows Certificate Store `CurrentUser\My`, dùng Windows CSP/CNG để ký `RSA-SHA256` và trả về chữ ký Base64. Khi ký, Bridge mở tiến trình PowerShell tương tác để CSP/CNG có thể hiện hộp thoại PIN. Private key không rời USB Token; mã PIN chỉ được nhập trong cửa sổ CSP/Token Manager do NC-CA cung cấp.

## Cài đặt

1. Cài driver/Token Manager hoặc Plugin NC-CA chính thức và cắm USB Token. Kiểm tra chứng thư hoạt động trước trên phần mềm do NC-CA cung cấp.
2. Mở PowerShell tại thư mục này và chạy (chỉ cần nếu chưa có môi trường `KSK_API/.venv`):

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install_bridge.ps1
   ```

3. Khởi động Bridge trong cửa sổ PowerShell đó. Script có thể dùng lại môi trường Python của `KSK_API` nếu đã tồn tại:

   ```powershell
   .\start_bridge.ps1
   ```

4. Kiểm tra `http://127.0.0.1:18181/health`; kết quả phải có `status: ok`.

## Khi không thấy chứng thư số

Bridge chỉ có thể chọn chứng thư hiện diện trong `CurrentUser\My` của **đúng tài khoản Windows đã chạy** `start_bridge.ps1`. Trước khi ký, mở PowerShell thông thường (không phải `Run as administrator`) và kiểm tra:

```powershell
certutil -user -store My
```

Kết quả phải có ít nhất một chứng thư của Token kèm private key. Nếu kho trống như vậy:

1. Rút/cắm lại USB Token NC-CA và kiểm tra đèn thiết bị.
2. Cài hoặc cập nhật driver/Token Manager/Plugin NC-CA chính thức, sau đó đóng hẳn trình duyệt và mở lại.
3. Mở Token Manager NC-CA để xác nhận chứng thư còn hiệu lực và Windows nhận Token.
4. Đóng rồi chạy lại `start_bridge.ps1` bằng chính tài khoản Windows đang mở Chrome/Edge.

Không chạy Bridge bằng `Run as administrator` nếu trình duyệt mở bằng tài khoản thường: hai tài khoản có Certificate Store khác nhau. Không thử PIN lặp lại khi chưa chắc PIN đúng để tránh khóa Token.

## Dùng với lienthong.html

1. Mở `http://localhost:5500/lienthong.html` trên **cùng máy cắm Token**.
2. Chọn **Chọn chứng thư số / USB Token**.
3. Nhập `http://127.0.0.1:18181`, bấm **Chọn chứng thư số / USB Token**, chọn chứng thư rồi bấm **Ký XML bằng USB Token**.
4. Khi CSP/Token Manager hiện hộp thoại, kiểm tra chứng thư và nhập PIN tại hộp thoại đó. Bridge trả chữ ký Base64 vào trường `signature` của trang.

Không nhập PIN, không tải private key và không dán PIN vào HTML/API.

## CORS và an toàn

Mặc định Bridge chỉ chấp nhận yêu cầu từ `http://localhost:5500` và `http://127.0.0.1:5500`. Nếu mở KSK ở một origin khác, trước khi khởi động Bridge hãy tạo biến môi trường chỉ gồm các origin tin cậy, ví dụ:

```powershell
$env:NCCA_SIGNER_ORIGINS = 'http://192.168.1.10:5500,http://localhost:5500'
.\start_bridge.ps1
```

Không dùng `*`, không đưa Bridge ra LAN và không chạy dưới Windows Service: Certificate Store của dịch vụ không phải tài khoản đang cắm Token.

## Lưu ý về HSSK

Bridge ký đúng chuỗi UTF-8 mà `lienthong.html` gửi đến và trả chữ ký RSA-SHA256 Base64. Hiện trang gửi XML gốc. Tài liệu HSSK Hà Nội mô tả trường `signature` nhưng chưa công bố chính xác chuỗi cần ký (XML gốc, `data.content` Base64 hay JSON chuẩn hóa). Chỉ đẩy dữ liệu thật sau khi đầu mối HSSK xác nhận nội dung ký; khi đó có thể đổi dữ liệu gửi vào Bridge mà không làm lộ PIN/private key.
