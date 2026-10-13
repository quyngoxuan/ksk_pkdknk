using System.Drawing.Imaging;
using System.Drawing.Drawing2D;

namespace KskLienthong;

internal sealed class SignatureImageForm : Form
{
    private const long MaxPixels = 40_000_000;
    private const int MaxWidth = 1600;
    private const int MaxHeight = 900;

    private readonly PictureBox _originalPreview = new() { Dock = DockStyle.Fill, SizeMode = PictureBoxSizeMode.Zoom, BackColor = Color.White };
    private readonly PictureBox _processedPreview = new() { Dock = DockStyle.Fill, SizeMode = PictureBoxSizeMode.Zoom, BackColor = Color.White };
    private readonly Label _fileLabel = new() { AutoEllipsis = true, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
    private readonly Label _sizeLabel = new() { AutoSize = true, ForeColor = SystemColors.GrayText };
    private readonly CheckBox _removeBackground = new() { Text = "Tách nền trắng/sáng", Checked = true, AutoSize = true };
    private readonly TrackBar _threshold = new() { Minimum = 220, Maximum = 250, Value = 238, TickFrequency = 5, Width = 190 };
    private readonly Label _thresholdValue = new() { AutoSize = true, Text = "238" };
    private readonly TextBox _base64Output = new() { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, WordWrap = false, Font = new Font("Consolas", 9) };
    private readonly Button _encodeButton = new() { Text = "Mã hóa Base64", AutoSize = true, Enabled = false };
    private readonly Button _copyButton = new() { Text = "Sao chép", AutoSize = true, Enabled = false };
    private readonly Button _saveButton = new() { Text = "Lưu chuỗi ra .txt…", AutoSize = true, Enabled = false };
    private Bitmap? _sourceImage;
    private Bitmap? _processedImage;
    private string? _selectedPath;

    public SignatureImageForm()
    {
        Text = "Mã hóa ảnh chữ ký bác sĩ thành Base64";
        Width = 1120;
        Height = 820;
        MinimumSize = new Size(900, 650);
        StartPosition = FormStartPosition.CenterParent;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 1, RowCount = 5 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 54));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 52));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));

        var notice = new Label
        {
            Text = "Công cụ này tạo ảnh PNG nền trong suốt và chuỗi Base64 để chèn ảnh chữ ký. Đây không phải chữ ký số, không thay thế thao tác ký bằng USB Token.",
            Dock = DockStyle.Fill,
            ForeColor = Color.DarkSlateBlue,
            TextAlign = ContentAlignment.MiddleLeft,
            AutoEllipsis = true
        };
        layout.Controls.Add(notice, 0, 0);

        var toolbar = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false, AutoScroll = true, FlowDirection = FlowDirection.LeftToRight, Padding = new Padding(0, 7, 0, 0) };
        var choose = new Button { Text = "Chọn ảnh…", AutoSize = true };
        choose.Click += (_, _) => ChooseImage();
        toolbar.Controls.Add(choose);
        toolbar.Controls.Add(_fileLabel);
        _fileLabel.Width = 245;
        toolbar.Controls.Add(_removeBackground);
        toolbar.Controls.Add(new Label { Text = "Ngưỡng nền:", AutoSize = true, Padding = new Padding(8, 8, 0, 0) });
        _threshold.ValueChanged += (_, _) => _thresholdValue.Text = _threshold.Value.ToString();
        toolbar.Controls.Add(_threshold);
        toolbar.Controls.Add(_thresholdValue);
        _encodeButton.Click += (_, _) => EncodeImage();
        toolbar.Controls.Add(_encodeButton);
        layout.Controls.Add(toolbar, 0, 1);

        var previews = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2, Padding = new Padding(0, 4, 0, 8) };
        previews.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        previews.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        previews.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        previews.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        previews.Controls.Add(new Label { Text = "Ảnh gốc", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 0);
        previews.Controls.Add(new Label { Text = "Ảnh sau xử lý (nền trong suốt)", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 1, 0);
        previews.Controls.Add(new Panel { Dock = DockStyle.Fill, Padding = new Padding(1), BackColor = SystemColors.ControlDark, Controls = { _originalPreview } }, 0, 1);
        previews.Controls.Add(new Panel { Dock = DockStyle.Fill, Padding = new Padding(1), BackColor = SystemColors.ControlDark, Controls = { _processedPreview } }, 1, 1);
        layout.Controls.Add(previews, 0, 2);

        var outputPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        outputPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        outputPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        outputPanel.Controls.Add(_sizeLabel, 0, 0);
        outputPanel.Controls.Add(_base64Output, 0, 1);
        layout.Controls.Add(outputPanel, 0, 3);

        var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
        var close = new Button { Text = "Đóng", AutoSize = true, DialogResult = DialogResult.Cancel };
        _copyButton.Click += (_, _) => CopyBase64();
        _saveButton.Click += (_, _) => SaveBase64();
        actions.Controls.Add(close);
        actions.Controls.Add(_saveButton);
        actions.Controls.Add(_copyButton);
        layout.Controls.Add(actions, 0, 4);

        Controls.Add(layout);
        CancelButton = close;
        FormClosed += (_, _) => DisposeImages();
    }

    private void ChooseImage()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Chọn ảnh chữ ký",
            Filter = "Ảnh chữ ký|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff|Tất cả tệp|*.*",
            CheckFileExists = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;

        try
        {
            using var loaded = new Bitmap(dialog.FileName);
            if ((long)loaded.Width * loaded.Height > MaxPixels)
                throw new InvalidOperationException("Ảnh quá lớn (trên 40 megapixel). Vui lòng chọn ảnh nhỏ hơn.");

            DisposeImages();
            _sourceImage = new Bitmap(loaded.Width, loaded.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(_sourceImage))
            {
                graphics.CompositingMode = CompositingMode.SourceCopy;
                graphics.DrawImage(loaded, 0, 0, loaded.Width, loaded.Height);
            }
            _selectedPath = dialog.FileName;
            _fileLabel.Text = Path.GetFileName(dialog.FileName);
            _originalPreview.Image = _sourceImage;
            _processedPreview.Image = null;
            _base64Output.Clear();
            _sizeLabel.Text = $"Ảnh gốc: {_sourceImage.Width} × {_sourceImage.Height}. Chọn ‘Mã hóa Base64’ để tách nền và tạo kết quả.";
            _encodeButton.Enabled = true;
            _copyButton.Enabled = false;
            _saveButton.Enabled = false;
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"Không đọc được ảnh đã chọn.\r\n\r\n{ex.Message}", "Ảnh không hợp lệ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void EncodeImage()
    {
        if (_sourceImage is null) return;
        try
        {
            using var prepared = _removeBackground.Checked
                ? RemoveLightBackground(_sourceImage, _threshold.Value)
                : new Bitmap(_sourceImage);
            using var cropped = CropTransparentMargins(prepared);
            using var resized = ResizeToFit(cropped, MaxWidth, MaxHeight);
            _processedImage?.Dispose();
            _processedImage = new Bitmap(resized);
            _processedPreview.Image = _processedImage;

            using var memory = new MemoryStream();
            _processedImage.Save(memory, ImageFormat.Png);
            var bytes = memory.ToArray();
            _base64Output.Text = Convert.ToBase64String(bytes);
            _sizeLabel.Text = $"Kích thước đầu ra: {_processedImage.Width} × {_processedImage.Height} · PNG {FormatBytes(bytes.Length)} · Base64 {FormatBytes(_base64Output.Text.Length)} ký tự";
            _copyButton.Enabled = true;
            _saveButton.Enabled = true;
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"Không thể xử lý ảnh.\r\n\r\n{ex.Message}", "Lỗi mã hóa", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static Bitmap RemoveLightBackground(Bitmap source, int threshold)
    {
        var result = new Bitmap(source.Width, source.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(result)) graphics.DrawImage(source, 0, 0, source.Width, source.Height);
        var bounds = new Rectangle(0, 0, result.Width, result.Height);
        var data = result.LockBits(bounds, ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
        try
        {
            unsafe
            {
                for (var y = 0; y < result.Height; y++)
                {
                    var row = (byte*)data.Scan0 + y * data.Stride;
                    for (var x = 0; x < result.Width; x++)
                    {
                        var pixel = row + x * 4;
                        var blue = pixel[0];
                        var green = pixel[1];
                        var red = pixel[2];
                        var darkest = Math.Min(red, Math.Min(green, blue));
                        var alpha = 255 - darkest;
                        var transparentCutoff = 255 - threshold;
                        if (alpha <= transparentCutoff)
                        {
                            pixel[0] = pixel[1] = pixel[2] = pixel[3] = 0;
                            continue;
                        }

                        // Estimate the ink color against a white background and retain the antialiased edge as alpha.
                        var backgroundPart = 255 - alpha;
                        pixel[0] = Unblend(blue, backgroundPart, alpha);
                        pixel[1] = Unblend(green, backgroundPart, alpha);
                        pixel[2] = Unblend(red, backgroundPart, alpha);
                        pixel[3] = (byte)Math.Clamp(alpha, 0, 255);
                    }
                }
            }
        }
        catch
        {
            result.UnlockBits(data);
            result.Dispose();
            throw;
        }
        result.UnlockBits(data);
        return result;
    }

    private static byte Unblend(byte channel, int backgroundPart, int alpha)
    {
        if (alpha <= 0) return 0;
        return (byte)Math.Clamp((channel - backgroundPart) * 255 / alpha, 0, 255);
    }

    private static Bitmap CropTransparentMargins(Bitmap source)
    {
        var left = source.Width;
        var top = source.Height;
        var right = -1;
        var bottom = -1;
        var bounds = new Rectangle(0, 0, source.Width, source.Height);
        var data = source.LockBits(bounds, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            unsafe
            {
                for (var y = 0; y < source.Height; y++)
                {
                    var row = (byte*)data.Scan0 + y * data.Stride;
                    for (var x = 0; x < source.Width; x++)
                    {
                        if (row[x * 4 + 3] <= 8) continue;
                        left = Math.Min(left, x);
                        top = Math.Min(top, y);
                        right = Math.Max(right, x);
                        bottom = Math.Max(bottom, y);
                    }
                }
            }
        }
        finally { source.UnlockBits(data); }
        if (right < left || bottom < top) throw new InvalidOperationException("Không tìm thấy nét chữ ký. Hãy giảm ngưỡng tách nền hoặc chọn ảnh khác.");

        const int margin = 12;
        left = Math.Max(0, left - margin);
        top = Math.Max(0, top - margin);
        right = Math.Min(source.Width - 1, right + margin);
        bottom = Math.Min(source.Height - 1, bottom + margin);
        var crop = new Rectangle(left, top, right - left + 1, bottom - top + 1);
        var result = new Bitmap(crop.Width, crop.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(result))
        {
            graphics.CompositingMode = CompositingMode.SourceCopy;
            graphics.DrawImage(source, new Rectangle(0, 0, crop.Width, crop.Height), crop, GraphicsUnit.Pixel);
        }
        return result;
    }

    private static Bitmap ResizeToFit(Bitmap source, int maxWidth, int maxHeight)
    {
        var scale = Math.Min(1d, Math.Min((double)maxWidth / source.Width, (double)maxHeight / source.Height));
        var width = Math.Max(1, (int)Math.Round(source.Width * scale));
        var height = Math.Max(1, (int)Math.Round(source.Height * scale));
        var result = new Bitmap(width, height, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(result);
        graphics.CompositingMode = CompositingMode.SourceCopy;
        graphics.CompositingQuality = CompositingQuality.HighQuality;
        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        graphics.SmoothingMode = SmoothingMode.HighQuality;
        graphics.DrawImage(source, new Rectangle(0, 0, width, height));
        return result;
    }

    private void CopyBase64()
    {
        if (string.IsNullOrWhiteSpace(_base64Output.Text)) return;
        try
        {
            Clipboard.SetText(_base64Output.Text);
            MessageBox.Show(this, "Đã sao chép chuỗi Base64 vào clipboard.", "Mã hóa ảnh chữ ký", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"Không ghi được clipboard.\r\n\r\n{ex.Message}", "Lỗi sao chép", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void SaveBase64()
    {
        if (string.IsNullOrWhiteSpace(_base64Output.Text)) return;
        using var dialog = new SaveFileDialog
        {
            Title = "Lưu chuỗi Base64",
            Filter = "Tệp văn bản|*.txt|Tất cả tệp|*.*",
            FileName = $"{Path.GetFileNameWithoutExtension(_selectedPath ?? "chu-ky")}_base64.txt",
            DefaultExt = "txt",
            AddExtension = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        File.WriteAllText(dialog.FileName, _base64Output.Text, new System.Text.UTF8Encoding(false));
    }

    private static string FormatBytes(long bytes) => bytes < 1024 ? $"{bytes} B" : $"{bytes / 1024d:0.##} KB";

    private void DisposeImages()
    {
        _originalPreview.Image = null;
        _processedPreview.Image = null;
        _sourceImage?.Dispose();
        _processedImage?.Dispose();
        _sourceImage = null;
        _processedImage = null;
    }
}
