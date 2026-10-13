using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace KskLienthong;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new NativeHomeForm());
    }
}

internal sealed class NativeHomeForm : Form
{
    private AppSettings _settings = AppSettings.Load();

    public NativeHomeForm()
    {
        Text = "KSK Liên thông — Desktop";
        Width = 700;
        Height = 360;
        StartPosition = FormStartPosition.CenterScreen;
        var title = new Label { Text = "Liên thông hồ sơ khám sức khỏe", Font = new Font("Segoe UI", 18, FontStyle.Bold), AutoSize = true };
        var batch = new Button { Text = "Liên thông nhiều hồ sơ (mới)", Width = 260, Height = 54 };
        var single = new Button { Text = "Giao diện liên thông cũ (WebView2)", Width = 260, Height = 42 };
        var settings = new Button { Text = "Cấu hình API", Width = 120, Height = 42 };
        var status = new Label { Text = $"API: {_settings.ApiBaseUrl}\r\nChữ ký USB Token thực hiện trực tiếp trong ứng dụng native.", AutoSize = true, ForeColor = SystemColors.GrayText };
        batch.Click += (_, _) => { using var form = new BatchLinkageForm(_settings); form.ShowDialog(this); };
        single.Click += (_, _) => { using var form = new MainForm(); form.ShowDialog(this); _settings = AppSettings.Load(); };
        settings.Click += (_, _) =>
        {
            using var dialog = new SettingsForm(_settings);
            if (dialog.ShowDialog(this) == DialogResult.OK && dialog.Result is { } updated)
            {
                updated.Save(); _settings = updated;
                status.Text = $"API: {_settings.ApiBaseUrl}\r\nChữ ký USB Token thực hiện trực tiếp trong ứng dụng native.";
            }
        };
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(32), RowCount = 5, ColumnCount = 1 };
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 34));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 64));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 66));
        layout.Controls.Add(title, 0, 0);
        layout.Controls.Add(batch, 0, 1);
        layout.Controls.Add(single, 0, 2);
        layout.Controls.Add(settings, 0, 3);
        layout.Controls.Add(status, 0, 4);
        Controls.Add(layout);
    }
}

internal sealed class MainForm : Form
{
    private readonly WebView2 _webView = new() { Dock = DockStyle.Fill };
    private readonly Label _status = new() { AutoSize = true, Padding = new Padding(8), Text = "Đang khởi động Local Signer…" };
    private AppSettings _settings = AppSettings.Default;
    private WebApplication? _signer;

    public MainForm()
    {
        Text = "KSK – Liên thông HSSK Hà Nội";
        Width = 1440;
        Height = 920;
        MinimumSize = new Size(1000, 700);
        StartPosition = FormStartPosition.CenterScreen;
        var settingsItem = new ToolStripMenuItem("Cấu hình…");
        settingsItem.Click += (_, _) => Configure();
        var signatureImageItem = new ToolStripMenuItem("Mã hóa ảnh chữ ký Base64…");
        signatureImageItem.Click += (_, _) =>
        {
            using var form = new SignatureImageForm();
            form.ShowDialog(this);
        };
        var menu = new MenuStrip();
        menu.Items.Add(new ToolStripMenuItem("Thiết lập", null, settingsItem));
        menu.Items.Add(new ToolStripMenuItem("Công cụ", null, signatureImageItem));
        MainMenuStrip = menu;
        Controls.Add(menu);
        Controls.Add(_webView);
        Controls.Add(new StatusStrip { Items = { new ToolStripControlHost(_status) } });
        Shown += async (_, _) => await StartAsync();
        FormClosing += async (_, _) => await StopSignerAsync();
    }

    private async Task StartAsync()
    {
        try
        {
            _settings = AppSettings.Load();
            if (!File.Exists(AppSettings.IniPath)) _settings.Save();
            await StartSignerAsync();
            await _webView.EnsureCoreWebView2Async();
            _webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
            _webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
            var startupConfig = System.Text.Json.JsonSerializer.Serialize(_settings.ToWebConfig());
            await _webView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                $"window.KSK_DESKTOP_CONFIG={startupConfig};");
            _webView.CoreWebView2.DownloadStarting += HandleDownloadStarting;
            _webView.CoreWebView2.NavigationCompleted += (_, e) =>
            {
                _status.Text = e.IsSuccess
                    ? $"Đã tải giao diện. API: {_settings.ApiBaseUrl} · XML: {_settings.XmlOutputDirectory}"
                    : $"Không tải được giao diện/API tại {_settings.ApiBaseUrl}. Kiểm tra kết nối máy chủ.";
            };
            _webView.CoreWebView2.Navigate(AppUrl(_settings));
        }
        catch (Exception ex)
        {
            MessageBox.Show(this,
                $"Không thể khởi động ứng dụng.\n\n{ex.Message}\n\n" +
                "Đảm bảo WebView2 Runtime đã cài, API theo ini.txt đang chạy và cổng 18181 chưa bị Local Signer khác sử dụng.",
                "KSK Liên thông", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    private async Task StartSignerAsync()
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:18181");
        builder.Logging.ClearProviders();
        var app = builder.Build();
        app.Use(async (context, next) =>
        {
            var origin = context.Request.Headers.Origin.ToString();
            if (context.Request.Path == "/health" && string.IsNullOrEmpty(origin))
            {
                await next();
                return;
            }
            if (origin != _settings.ApiOrigin)
            {
                context.Response.StatusCode = StatusCodes.Status403Forbidden;
                await context.Response.WriteAsJsonAsync(new { detail = "Origin không được phép sử dụng chữ ký số." });
                return;
            }
            context.Response.Headers.AccessControlAllowOrigin = _settings.ApiOrigin;
            context.Response.Headers.AccessControlAllowMethods = "GET, POST, OPTIONS";
            context.Response.Headers.AccessControlAllowHeaders = "Content-Type";
            if (HttpMethods.IsOptions(context.Request.Method))
            {
                context.Response.StatusCode = StatusCodes.Status204NoContent;
                return;
            }
            await next();
        });

        app.MapGet("/health", () => Results.Ok(new { status = "ok", store = "CurrentUser/My", algorithm = "RSA-SHA256" }));
        app.MapGet("/certificates", () => Results.Ok(new { certificates = ReadCertificates() }));
        app.MapPost("/sign", (SignRequest request) => Sign(request));
        await app.StartAsync();
        _signer = app;
    }

    private static string AppUrl(AppSettings settings) => $"{settings.ApiBaseUrl.TrimEnd('/')}/lienthong.html";

    private void HandleDownloadStarting(object? sender, CoreWebView2DownloadStartingEventArgs e)
    {
        try
        {
            Directory.CreateDirectory(_settings.XmlOutputDirectory);
            var safeName = Path.GetFileName(e.ResultFilePath);
            if (string.IsNullOrWhiteSpace(safeName)) safeName = $"KSK_{DateTime.Now:yyyyMMdd_HHmmss}.xml";
            if (!safeName.EndsWith(".xml", StringComparison.OrdinalIgnoreCase)) safeName += ".xml";
            e.ResultFilePath = Path.Combine(_settings.XmlOutputDirectory, safeName);
            _status.Text = $"File XML sẽ lưu tại: {e.ResultFilePath}";
        }
        catch (Exception ex)
        {
            e.Cancel = true;
            MessageBox.Show(this, $"Không thể lưu file XML vào thư mục đã cấu hình.\n\n{ex.Message}",
                "Lỗi lưu XML", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async void Configure()
    {
        using var dialog = new SettingsForm(_settings);
        if (dialog.ShowDialog(this) != DialogResult.OK || dialog.Result is not { } updated) return;
        var apiChanged = !string.Equals(_settings.ApiBaseUrl, updated.ApiBaseUrl, StringComparison.OrdinalIgnoreCase);
        if (apiChanged && MessageBox.Show(this,
                "Thay đổi API sẽ tải lại giao diện và xóa dữ liệu chưa lưu trên trang. Tiếp tục?",
                "Đổi máy chủ API", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
            return;

        try
        {
            updated.Save();
            _settings = updated;
            if (_webView.CoreWebView2 is not null)
            {
                if (apiChanged)
                {
                    _webView.CoreWebView2.Navigate(AppUrl(_settings));
                }
                else
                {
                    var config = System.Text.Json.JsonSerializer.Serialize(_settings.ToWebConfig());
                    await _webView.CoreWebView2.ExecuteScriptAsync($"window.applyKskDesktopSettings?.({config});");
                    _status.Text = $"Đã lưu cấu hình. API: {_settings.ApiBaseUrl} · XML: {_settings.XmlOutputDirectory}";
                }
            }
            MessageBox.Show(this, $"Đã lưu cấu hình vào:\n{AppSettings.IniPath}", "Cấu hình", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"Không lưu được ini.txt.\n\n{ex.Message}", "Lỗi cấu hình", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static IReadOnlyList<CertificateInfo> ReadCertificates()
    {
        using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
        store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
        var result = new List<CertificateInfo>();
        foreach (var certificate in store.Certificates)
        {
            try
            {
                using var rsa = certificate.GetRSAPublicKey();
                if (rsa is null || !certificate.HasPrivateKey) continue;
                result.Add(new CertificateInfo(
                    certificate.Thumbprint ?? string.Empty,
                    certificate.Subject,
                    certificate.Issuer,
                    certificate.SerialNumber,
                    certificate.NotBefore.ToUniversalTime().ToString("O"),
                    certificate.NotAfter.ToUniversalTime().ToString("O"),
                    string.IsNullOrWhiteSpace(certificate.FriendlyName) ? null : certificate.FriendlyName));
            }
            catch (CryptographicException)
            {
                // Skip certificates whose provider cannot expose an RSA public key.
            }
        }
        return result;
    }

    private static IResult Sign(SignRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.CertificateId) || request.CertificateId.Length > 128 ||
            request.CertificateId.Any(c => !Uri.IsHexDigit(c)))
            return Results.BadRequest(new { detail = "certificate_id không hợp lệ." });
        if (string.IsNullOrEmpty(request.Content)) return Results.BadRequest(new { detail = "Nội dung ký rỗng." });
        if (Encoding.UTF8.GetByteCount(request.Content) > 2 * 1024 * 1024)
            return Results.Json(new { detail = "Nội dung ký vượt quá 2 MiB." }, statusCode: StatusCodes.Status413PayloadTooLarge);
        if (request.ContentEncoding != "utf-8") return Results.BadRequest(new { detail = "Chỉ chấp nhận nội dung UTF-8." });

        try
        {
            using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
            store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
            var thumbprint = request.CertificateId.Replace(" ", "", StringComparison.Ordinal).ToUpperInvariant();
            var certificate = store.Certificates.Cast<X509Certificate2>()
                .FirstOrDefault(cert => string.Equals(cert.Thumbprint?.Replace(" ", "", StringComparison.Ordinal), thumbprint, StringComparison.OrdinalIgnoreCase));
            if (certificate is null) return Results.NotFound(new { detail = "Không tìm thấy chứng thư đã chọn trong CurrentUser\\My." });

            using (certificate)
            using (var rsa = certificate.GetRSAPrivateKey())
            {
                if (rsa is null) return Results.BadRequest(new { detail = "Chứng thư không có khóa RSA hoặc Windows không truy cập được Token." });
                // The key operation is delegated to the Windows CSP/KSP. Any Token PIN prompt is owned by its provider.
                var signature = rsa.SignData(Encoding.UTF8.GetBytes(request.Content), HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                return Results.Ok(new SignResponse(Convert.ToBase64String(signature), certificate.Thumbprint ?? thumbprint));
            }
        }
        catch (CryptographicException)
        {
            return Results.Json(new { detail = "Windows CSP/KSP không thể ký. Kiểm tra Token, chứng thư và hộp thoại PIN của nhà cung cấp." }, statusCode: StatusCodes.Status503ServiceUnavailable);
        }
    }

    private async Task StopSignerAsync()
    {
        if (_signer is null) return;
        await _signer.StopAsync();
        await _signer.DisposeAsync();
        _signer = null;
    }
}

internal sealed record CertificateInfo(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("subject")] string Subject,
    [property: JsonPropertyName("issuer")] string Issuer,
    [property: JsonPropertyName("serial_number")] string SerialNumber,
    [property: JsonPropertyName("valid_from")] string ValidFrom,
    [property: JsonPropertyName("valid_to")] string ValidTo,
    [property: JsonPropertyName("friendly_name")] string? FriendlyName);

internal sealed record SignRequest(
    [property: JsonPropertyName("certificate_id")] string CertificateId,
    [property: JsonPropertyName("content")] string Content,
    [property: JsonPropertyName("content_encoding")] string ContentEncoding = "utf-8",
    [property: JsonPropertyName("purpose")] string Purpose = "hssk-kham-suc-khoe");

internal sealed record SignResponse(
    [property: JsonPropertyName("signature")] string Signature,
    [property: JsonPropertyName("certificate_id")] string CertificateId,
    [property: JsonPropertyName("algorithm")] string Algorithm = "RSA-SHA256");
