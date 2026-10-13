using System.Diagnostics;
using System.Text;

namespace KskApiController;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new ControllerApplicationContext());
    }
}

internal sealed class ControllerApplicationContext : ApplicationContext
{
    private readonly NotifyIcon _trayIcon;
    private readonly ToolStripMenuItem _statusItem;
    private readonly ToolStripMenuItem _startItem;
    private readonly ToolStripMenuItem _stopItem;
    private readonly SynchronizationContext _uiContext;
    private Process? _apiProcess;
    private ApiControllerSettings _settings;

    public ControllerApplicationContext()
    {
        _uiContext = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
        _settings = ApiControllerSettings.Load();
        _statusItem = new ToolStripMenuItem();
        _startItem = new ToolStripMenuItem("Khởi động API", null, (_, _) => StartApi());
        _stopItem = new ToolStripMenuItem("Dừng API", null, (_, _) => StopApi());
        var menu = new ContextMenuStrip();
        menu.Items.AddRange([
            _statusItem,
            new ToolStripSeparator(),
            _startItem,
            _stopItem,
            new ToolStripMenuItem("Khởi động lại API", null, (_, _) => RestartApi()),
            new ToolStripSeparator(),
            new ToolStripMenuItem("Mở hệ thống KSK", null, (_, _) => OpenUrl($"http://{_settings.Host}:{_settings.Port}/main.html")),
            new ToolStripMenuItem("Mở Swagger", null, (_, _) => OpenUrl($"http://{_settings.Host}:{_settings.Port}/docs")),
            new ToolStripMenuItem("Mở nhật ký", null, (_, _) => OpenLog()),
            new ToolStripMenuItem("Cấu hình", null, (_, _) => Configure()),
            new ToolStripSeparator(),
            new ToolStripMenuItem("Thoát", null, (_, _) => ExitApplication()),
        ]);
        _trayIcon = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "KSK API Controller",
            ContextMenuStrip = menu,
            Visible = true,
        };
        _trayIcon.DoubleClick += (_, _) => ShowStatus();
        UpdateUi();
    }

    private void StartApi()
    {
        if (_apiProcess is { HasExited: false }) { ShowStatus(); return; }
        if (!File.Exists(_settings.PythonPath))
        {
            ShowError($"Không tìm thấy Python môi trường ảo:\n{_settings.PythonPath}\n\nHãy vào Cấu hình để sửa đường dẫn.");
            return;
        }
        if (!Directory.Exists(_settings.ApiDirectory))
        {
            ShowError($"Không tìm thấy thư mục KSK_API:\n{_settings.ApiDirectory}");
            return;
        }
        try
        {
            var logDirectory = Path.Combine(_settings.ApiDirectory, "logs");
            Directory.CreateDirectory(logDirectory);
            var info = new ProcessStartInfo
            {
                FileName = _settings.PythonPath,
                Arguments = $"-m uvicorn app.main:app --host {_settings.Host} --port {_settings.Port}",
                WorkingDirectory = _settings.ApiDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            _apiProcess = new Process { StartInfo = info, EnableRaisingEvents = true };
            _apiProcess.Exited += (_, _) => _uiContext.Post(_ => UpdateUi(), null);
            _apiProcess.Start();
            var logFile = Path.Combine(logDirectory, "api-controller.log");
            _ = PumpLogAsync(_apiProcess.StandardOutput, logFile);
            _ = PumpLogAsync(_apiProcess.StandardError, logFile);
            UpdateUi();
            _trayIcon.ShowBalloonTip(2500, "KSK API", "Đã khởi động API ở chế độ nền.", ToolTipIcon.Info);
        }
        catch (Exception ex) { ShowError($"Không thể khởi động API:\n{ex.Message}"); }
    }

    private async Task PumpLogAsync(StreamReader reader, string logFile)
    {
        while (await reader.ReadLineAsync() is { } line)
            await File.AppendAllTextAsync(logFile, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {line}{Environment.NewLine}", Encoding.UTF8);
    }

    private void StopApi()
    {
        if (_apiProcess is not { HasExited: false }) { UpdateUi(); return; }
        try
        {
            _apiProcess.Kill(entireProcessTree: true);
            _apiProcess.WaitForExit(5000);
            _trayIcon.ShowBalloonTip(2000, "KSK API", "Đã dừng tiến trình API do ứng dụng này khởi động.", ToolTipIcon.Info);
        }
        catch (Exception ex) { ShowError($"Không thể dừng API:\n{ex.Message}"); }
        finally { UpdateUi(); }
    }

    private void RestartApi() { StopApi(); StartApi(); }

    private void Configure()
    {
        using var form = new SettingsForm(_settings);
        if (form.ShowDialog() != DialogResult.OK) return;
        _settings = form.Settings;
        _settings.Save();
        UpdateUi();
    }

    private void OpenLog()
    {
        var logDirectory = Path.Combine(_settings.ApiDirectory, "logs");
        Directory.CreateDirectory(logDirectory);
        Process.Start(new ProcessStartInfo { FileName = logDirectory, UseShellExecute = true });
    }

    private static void OpenUrl(string url) => Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });

    private void ShowStatus()
    {
        var running = _apiProcess is { HasExited: false };
        MessageBox.Show(running ? $"API đang chạy.\nPID: {_apiProcess!.Id}\nURL: http://{_settings.Host}:{_settings.Port}" : "API đang dừng.", "KSK API Controller", MessageBoxButtons.OK, running ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
    }

    private void UpdateUi()
    {
        var running = _apiProcess is { HasExited: false };
        _statusItem.Text = running ? $"● API đang chạy · cổng {_settings.Port}" : "● API đang dừng";
        _statusItem.ForeColor = running ? Color.ForestGreen : Color.Firebrick;
        _startItem.Enabled = !running;
        _stopItem.Enabled = running;
        _trayIcon.Text = running ? $"KSK API đang chạy · cổng {_settings.Port}" : "KSK API đang dừng";
    }

    private static void ShowError(string text) => MessageBox.Show(text, "KSK API Controller", MessageBoxButtons.OK, MessageBoxIcon.Error);

    private void ExitApplication()
    {
        if (_apiProcess is { HasExited: false } && MessageBox.Show("API đang chạy. Dừng API và thoát?", "KSK API Controller", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes) StopApi();
        _trayIcon.Visible = false;
        _trayIcon.Dispose();
        ExitThread();
    }
}

internal sealed record ApiControllerSettings(string ApiDirectory, string PythonPath, string Host, int Port)
{
    private static string FilePath => Path.Combine(AppContext.BaseDirectory, "KskApiController.ini");
    public static ApiControllerSettings Default => new(@"C:\PKNK_KSK\KSK_API", @"C:\PKNK_KSK\KSK_API\.venv\Scripts\python.exe", "0.0.0.0", 5500);

    public static ApiControllerSettings Load()
    {
        if (!File.Exists(FilePath)) { var initialSettings = Default; initialSettings.Save(); return initialSettings; }
        var values = File.ReadLines(FilePath).Select(line => line.Split('=', 2)).Where(parts => parts.Length == 2).ToDictionary(parts => parts[0].Trim(), parts => parts[1].Trim(), StringComparer.OrdinalIgnoreCase);
        var defaults = Default;
        return new ApiControllerSettings(values.GetValueOrDefault("ApiDirectory", defaults.ApiDirectory), values.GetValueOrDefault("PythonPath", defaults.PythonPath), values.GetValueOrDefault("Host", defaults.Host), int.TryParse(values.GetValueOrDefault("Port"), out var port) ? port : defaults.Port);
    }

    public void Save() => File.WriteAllLines(FilePath, [$"ApiDirectory={ApiDirectory}", $"PythonPath={PythonPath}", $"Host={Host}", $"Port={Port}"]);
}

internal sealed class SettingsForm : Form
{
    private readonly TextBox _directory;
    private readonly TextBox _python;
    private readonly TextBox _host;
    private readonly NumericUpDown _port;
    public ApiControllerSettings Settings { get; private set; }

    public SettingsForm(ApiControllerSettings settings)
    {
        Settings = settings;
        Text = "Cấu hình KSK API Controller";
        StartPosition = FormStartPosition.CenterScreen;
        Width = 680; Height = 280; FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
        _directory = new TextBox { Text = settings.ApiDirectory, Dock = DockStyle.Fill };
        _python = new TextBox { Text = settings.PythonPath, Dock = DockStyle.Fill };
        _host = new TextBox { Text = settings.Host, Dock = DockStyle.Fill };
        _port = new NumericUpDown { Minimum = 1, Maximum = 65535, Value = settings.Port, Dock = DockStyle.Left, Width = 140 };
        var grid = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 2, RowCount = 5 };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150)); grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        AddRow(grid, 0, "Thư mục KSK_API", _directory); AddRow(grid, 1, "Python .venv", _python); AddRow(grid, 2, "Host", _host); AddRow(grid, 3, "Cổng", _port);
        var save = new Button { Text = "Lưu", DialogResult = DialogResult.OK, AutoSize = true }; var cancel = new Button { Text = "Hủy", DialogResult = DialogResult.Cancel, AutoSize = true };
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Right, AutoSize = true }; buttons.Controls.AddRange([save, cancel]); grid.Controls.Add(buttons, 1, 4);
        AcceptButton = save; CancelButton = cancel; Controls.Add(grid);
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (DialogResult == DialogResult.OK) Settings = new ApiControllerSettings(_directory.Text.Trim(), _python.Text.Trim(), _host.Text.Trim(), Decimal.ToInt32(_port.Value));
        base.OnFormClosing(e);
    }

    private static void AddRow(TableLayoutPanel grid, int row, string label, Control control)
    {
        grid.Controls.Add(new Label { Text = label, AutoSize = true, Anchor = AnchorStyles.Left }, 0, row);
        grid.Controls.Add(control, 1, row);
    }
}
