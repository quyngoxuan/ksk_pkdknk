# KSK API Controller

Ứng dụng Windows chạy ở System Tray để quản lý FastAPI KSK.

## Chạy khi phát triển

```powershell
cd C:\PKNK_KSK\KSK_API_Controller
dotnet run
```

## Đóng gói EXE

```powershell
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true
```

Sau khi chạy lần đầu, chỉnh `KskApiController.ini` nằm cạnh EXE nếu đường dẫn `KSK_API`, Python hoặc cổng khác mặc định.
