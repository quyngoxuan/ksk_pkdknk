namespace KskLienthong;

internal sealed class SettingsForm : Form
{
    private readonly TextBox _api = new();
    private readonly TextBox _xmlDirectory = new();
    private readonly TextBox _xmlPattern = new();
    private readonly TextBox _batchApiKey = new() { UseSystemPasswordChar = true };

    public AppSettings? Result { get; private set; }

    public SettingsForm(AppSettings current)
    {
        Text = "Cấu hình KSK Liên thông";
        Width = 720;
        Height = 385;
        MinimumSize = new Size(650, 350);
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;

        _api.Text = current.ApiBaseUrl;
        _xmlDirectory.Text = current.XmlOutputDirectory;
        _xmlPattern.Text = current.XmlFileNamePattern;
        _batchApiKey.Text = current.BatchApiKey;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 3, RowCount = 6 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 190));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));

        AddRow(layout, 0, "API gốc (không gồm /api/v1)", _api,
            "Ví dụ: http://localhost:5500 (ứng dụng tự nối /api/v1)");
        AddRow(layout, 1, "Thư mục vật lý lưu XML", _xmlDirectory, "");
        AddRow(layout, 2, "Mẫu tên file XML ({examId})", _xmlPattern,
            "Dùng {examId} để đặt mã lần khám vào tên file.");

        var browse = new Button { Text = "Chọn thư mục…", Dock = DockStyle.Fill };
        browse.Click += (_, _) => BrowseForFolder();
        layout.Controls.Add(browse, 2, 1);
        AddRow(layout, 3, "Batch API key", _batchApiKey,
            "Cùng giá trị KSK_BATCH_API_KEY trên API server; được mã hóa theo tài khoản Windows trong ini.txt.");

        var hint = new Label
        {
            Text = $"File cấu hình: {AppSettings.IniPath}\r\nXML chỉ được ghi ra thư mục này khi bấm ‘Tải file XML’.",
            Dock = DockStyle.Fill,
            ForeColor = SystemColors.GrayText,
            TextAlign = ContentAlignment.MiddleLeft
        };
        layout.Controls.Add(hint, 0, 4);
        layout.SetColumnSpan(hint, 3);

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
        var save = new Button { Text = "Lưu cấu hình", DialogResult = DialogResult.OK, AutoSize = true };
        var cancel = new Button { Text = "Hủy", DialogResult = DialogResult.Cancel, AutoSize = true };
        save.Click += (_, e) =>
        {
            if (!TryGetSettings(out var settings, out var error))
            {
                MessageBox.Show(this, error, "Kiểm tra cấu hình", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                DialogResult = DialogResult.None;
                return;
            }
            Result = settings;
        };
        buttons.Controls.Add(save);
        buttons.Controls.Add(cancel);
        layout.Controls.Add(buttons, 0, 5);
        layout.SetColumnSpan(buttons, 3);
        Controls.Add(layout);
        AcceptButton = save;
        CancelButton = cancel;
    }

    private static void AddRow(TableLayoutPanel layout, int row, string label, Control field, string helper)
    {
        var caption = new Label { Text = label, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
        field.Dock = DockStyle.Fill;
        layout.Controls.Add(caption, 0, row);
        layout.Controls.Add(field, 1, row);
        if (!string.IsNullOrWhiteSpace(helper))
            field.AccessibleDescription = helper;
    }

    private void BrowseForFolder()
    {
        using var picker = new FolderBrowserDialog { Description = "Chọn thư mục lưu file XML được tạo" };
        if (Directory.Exists(_xmlDirectory.Text)) picker.SelectedPath = _xmlDirectory.Text;
        if (picker.ShowDialog(this) == DialogResult.OK) _xmlDirectory.Text = picker.SelectedPath;
    }

    private bool TryGetSettings(out AppSettings settings, out string error)
    {
        settings = AppSettings.Default;
        error = "";
        var api = _api.Text.Trim().TrimEnd('/');
        if (!Uri.TryCreate(api, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) ||
            !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment) || !string.IsNullOrEmpty(uri.UserInfo))
        {
            error = "Địa chỉ API phải là URL http:// hoặc https:// hợp lệ.";
            return false;
        }
        if (!string.IsNullOrWhiteSpace(_batchApiKey.Text) && uri.Scheme == Uri.UriSchemeHttp && !uri.IsLoopback)
        {
            error = "Batch API key chỉ được gửi qua HTTPS; HTTP chỉ được dùng khi API chạy trên localhost/127.0.0.1.";
            return false;
        }
        var xmlDirectory = _xmlDirectory.Text.Trim();
        if (string.IsNullOrWhiteSpace(xmlDirectory) || !Path.IsPathFullyQualified(xmlDirectory))
        {
            error = "Thư mục lưu XML phải là đường dẫn vật lý đầy đủ, ví dụ C:\\PKNK_KSK\\XML.";
            return false;
        }
        var pattern = _xmlPattern.Text.Trim();
        if (string.IsNullOrWhiteSpace(pattern) || pattern.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            pattern.Contains('/') || pattern.Contains('\\') || !pattern.Contains("{examId}", StringComparison.Ordinal))
        {
            error = "Tên file phải hợp lệ, không chứa đường dẫn và cần có biến {examId}, ví dụ KSK_{examId}.xml.";
            return false;
        }
        if (!pattern.EndsWith(".xml", StringComparison.OrdinalIgnoreCase)) pattern += ".xml";
        var apiPath = uri.AbsolutePath.TrimEnd('/');
        if (apiPath.EndsWith("/api/v1", StringComparison.OrdinalIgnoreCase)) apiPath = apiPath[..^7];
        settings = new AppSettings(uri.GetLeftPart(UriPartial.Authority).ToLowerInvariant() + apiPath,
            Path.GetFullPath(xmlDirectory), pattern, _batchApiKey.Text.Trim());
        return true;
    }
}
