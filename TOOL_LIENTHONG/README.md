# KSK Liên thông Desktop

Ứng dụng Windows bọc giao diện `lienthong.html` hiện có trong WebView2 và cung cấp Local Signer tích hợp C# tại `127.0.0.1:18181`. FastAPI/SQL Server hiện hữu không bị thay đổi. Khóa riêng/PIN không được đọc hay lưu bởi ứng dụng; thao tác RSA-SHA256 được giao cho Windows CSP/KSP của Token.

## Chạy thử trên máy phát triển

1. Cài WebView2 Evergreen Runtime và driver/Token Manager chính thức của NC-CA; cắm Token và đăng nhập Windows bằng tài khoản cần ký.
2. Khởi động FastAPI như hiện tại tại cổng 5500. Trang `http://localhost:5500/lienthong.html` phải mở được.
3. Đóng Local Signer Bridge Python nếu đang chạy, vì ứng dụng C# dùng cùng cổng loopback 18181.
4. Từ thư mục này chạy `dotnet restore`, sau đó `dotnet run`.
5. Trong trang liên thông, chọn USB Token, chọn chứng thư rồi thực hiện ký. Nhà cung cấp CSP/KSP có thể hiện hộp thoại PIN khi gọi ký; nhập PIN chỉ vào hộp thoại Token. Không thử nhiều PIN khi chưa chắc mã đúng.

## Cấu hình ứng dụng

Mở menu **Thiết lập → Cấu hình…** để đặt:

- Địa chỉ API gốc, ví dụ `http://localhost:5500` (ứng dụng tự nối `/api/v1` và mở `lienthong.html`).
- Thư mục vật lý lưu XML. Nút **Tải file XML** sẽ ghi file vào thư mục này.
- Mẫu tên file, mặc định `KSK_{examId}.xml`; `{examId}` được thay bằng mã lần khám.

Cấu hình được ghi vào `ini.txt` cạnh EXE (tự tạo với giá trị mặc định khi chạy lần đầu). File này chỉ có URL và đường dẫn, không chứa thông tin Token/PIN. Nếu đổi API sang máy chủ khác, trang được tải lại nên cần lưu dữ liệu đang nhập trước.

## Đóng gói EXE

Đã publish thử được file `publish\KskLienthong.exe` dạng framework-dependent. Trên máy đích cần cài .NET 8 Desktop Runtime, WebView2 Evergreen Runtime và driver NC-CA. Để tạo lại:

```powershell
dotnet restore .\KskLienthong.Desktop.csproj
dotnet publish .\KskLienthong.Desktop.csproj -c Release --no-restore -p:UseAppHost=true -o .\publish
```

Muốn publish self-contained (không cần cài .NET Desktop Runtime) thì dùng lệnh dưới đây trên máy có kết nối NuGet ổn định:

```powershell
dotnet publish .\KskLienthong.Desktop.csproj -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
  -o .\publish
```

Chạy `publish\KskLienthong.exe` trên máy có WebView2 Runtime, API tại cổng 5500 và driver NC-CA. Bản publish không đóng gói API, SQL Server hay driver USB Token.

## Kiểm thử Token

Có thể kiểm tra `http://127.0.0.1:18181/health` khi ứng dụng đang mở. Thử liệt kê chứng thư và ký XML thử trước, xác minh chữ ký bằng chứng thư tương ứng. Việc hộp thoại PIN xuất hiện tùy cấu hình CSP/KSP/Token Manager của NC-CA; chưa thể xác nhận hành vi đó nếu máy không có Token/driver thực tế. Không gửi dữ liệu thật cho cổng HSSK đến khi đơn vị tiếp nhận xác nhận chính xác bytes/chuỗi cần ký.

Local Signer chỉ bind loopback và chỉ chấp nhận Origin `http://localhost:5500`. Nếu trang mở qua origin khác, yêu cầu bị từ chối.
