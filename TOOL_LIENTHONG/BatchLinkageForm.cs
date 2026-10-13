using System.ComponentModel;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace KskLienthong;

internal sealed class BatchLinkageForm : Form
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly AppSettings _settings;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(90) };
    private readonly ComboBox _companies = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 340 };
    private readonly ComboBox _campaigns = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 340, Enabled = false };
    private readonly ComboBox _certificates = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 420 };
    private readonly DataGridView _grid = new() { Dock = DockStyle.Fill, AllowUserToAddRows = false, AutoGenerateColumns = false, SelectionMode = DataGridViewSelectionMode.FullRowSelect };
    private readonly BindingList<BatchExamRow> _rows = [];
    private readonly Label _status = new() { AutoSize = true, Text = "Chọn đơn vị và đợt khám để tải hồ sơ." };
    private readonly Button _load = new() { Text = "Tải hồ sơ", AutoSize = true };
    private readonly Button _run = new() { Text = "Tạo batch, ký và gửi hồ sơ đã chọn", AutoSize = true, Enabled = false };
    private readonly List<X509Certificate2> _ownedCertificates = [];

    public BatchLinkageForm(AppSettings settings)
    {
        _settings = settings;
        Text = "Liên thông nhiều hồ sơ — native signing";
        Width = 1280;
        Height = 780;
        MinimumSize = new Size(1000, 600);
        StartPosition = FormStartPosition.CenterParent;
        _http.BaseAddress = new Uri(settings.ApiBaseUrl.TrimEnd('/') + "/api/v1/");

        ConfigureGrid();
        var filter = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true, Padding = new Padding(6) };
        filter.Controls.Add(new Label { Text = "Đơn vị", AutoSize = true, Padding = new Padding(0, 8, 0, 0) });
        filter.Controls.Add(_companies);
        filter.Controls.Add(new Label { Text = "Đợt khám", AutoSize = true, Padding = new Padding(6, 8, 0, 0) });
        filter.Controls.Add(_campaigns);
        filter.Controls.Add(_load);

        var certificateBar = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true, Padding = new Padding(6) };
        certificateBar.Controls.Add(new Label { Text = "Chứng thư ký", AutoSize = true, Padding = new Padding(0, 8, 0, 0) });
        certificateBar.Controls.Add(_certificates);
        certificateBar.Controls.Add(new Label { Text = "Token ký tuần tự từng XML; PIN chỉ nhập trong hộp thoại của CSP/KSP.", AutoSize = true, Padding = new Padding(0, 8, 0, 0) });

        var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(6) };
        var selectReady = new Button { Text = "Chọn hồ sơ đủ điều kiện", AutoSize = true };
        var clearSelection = new Button { Text = "Bỏ chọn", AutoSize = true };
        var history = new Button { Text = "Xem nhật ký batch", AutoSize = true };
        history.Click += async (_, _) => await ShowBatchHistoryAsync();
        actions.Controls.Add(selectReady); actions.Controls.Add(clearSelection); actions.Controls.Add(_run); actions.Controls.Add(history);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(12), ColumnCount = 1, RowCount = 5 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 54));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.Controls.Add(filter, 0, 0); layout.Controls.Add(certificateBar, 0, 1);
        layout.Controls.Add(_grid, 0, 2); layout.Controls.Add(actions, 0, 3); layout.Controls.Add(_status, 0, 4);
        Controls.Add(layout);

        _companies.SelectedIndexChanged += async (_, _) => await LoadCampaignsAsync();
        _load.Click += async (_, _) => await LoadExamsAsync();
        selectReady.Click += (_, _) => { foreach (var row in _rows) row.Selected = row.Ready; _grid.Refresh(); UpdateRunEnabled(); };
        clearSelection.Click += (_, _) => { foreach (var row in _rows) row.Selected = false; _grid.Refresh(); UpdateRunEnabled(); };
        _grid.CellValueChanged += (_, _) => UpdateRunEnabled();
        _certificates.SelectedIndexChanged += (_, _) => UpdateRunEnabled();
        _grid.CurrentCellDirtyStateChanged += (_, _) => { if (_grid.IsCurrentCellDirty) _grid.CommitEdit(DataGridViewDataErrorContexts.Commit); };
        _run.Click += async (_, _) => await RunBatchAsync();
        Load += async (_, _) => { await LoadCertificatesAsync(); await LoadCompaniesAsync(); };
        FormClosed += (_, _) => { _http.Dispose(); foreach (var cert in _ownedCertificates) cert.Dispose(); };
    }

    private void ConfigureGrid()
    {
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { DataPropertyName = nameof(BatchExamRow.Selected), HeaderText = "Gửi", Width = 45 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.ExamId), HeaderText = "ExamId", Width = 75, ReadOnly = true });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.PatientName), HeaderText = "Họ tên", Width = 190, ReadOnly = true });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.Shs), HeaderText = "SHS", Width = 90, ReadOnly = true });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.ExamCode), HeaderText = "Mã lần khám", Width = 170, ReadOnly = true });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.ReadinessText), HeaderText = "Điều kiện", Width = 100, ReadOnly = true });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.State), HeaderText = "Trạng thái batch", Width = 130, ReadOnly = true });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { DataPropertyName = nameof(BatchExamRow.Detail), HeaderText = "Lỗi / phản hồi", AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill, ReadOnly = true });
        _grid.DataSource = _rows;
        _grid.DataError += (_, e) => e.ThrowException = false;
    }

    private async Task LoadCompaniesAsync()
    {
        try
        {
            var items = await GetAsync<List<CompanyDto>>("companies?limit=500");
            _companies.DataSource = items; _companies.DisplayMember = nameof(CompanyDto.Name); _companies.ValueMember = nameof(CompanyDto.CompanyId);
        }
        catch (Exception ex) { SetStatus("Không tải được đơn vị: " + ex.Message); }
    }

    private async Task LoadCampaignsAsync()
    {
        _campaigns.DataSource = null; _campaigns.Enabled = false; _rows.Clear(); UpdateRunEnabled();
        if (_companies.SelectedItem is not CompanyDto company) return;
        try
        {
            var campaigns = await GetAsync<List<CampaignDto>>($"exam-campaigns?company_id={company.CompanyId}&limit=1000");
            _campaigns.DataSource = campaigns; _campaigns.DisplayMember = nameof(CampaignDto.CampaignName); _campaigns.ValueMember = nameof(CampaignDto.CampaignId); _campaigns.Enabled = campaigns.Count > 0;
        }
        catch (Exception ex) { SetStatus("Không tải được đợt khám: " + ex.Message); }
    }

    private async Task LoadExamsAsync()
    {
        if (_campaigns.SelectedItem is not CampaignDto campaign || _companies.SelectedItem is not CompanyDto company) return;
        SetBusy(true, "Đang tải hồ sơ và kiểm tra điều kiện liên thông…");
        try
        {
            var exams = await GetAsync<List<ExamDto>>($"exam-campaigns/{campaign.CampaignId}/exams?company_id={company.CompanyId}");
            _rows.Clear();
            foreach (var exam in exams)
            {
                var errors = exam.ReadinessErrors?.Select(e => e.FieldName).ToArray() ?? [];
                _rows.Add(new BatchExamRow { ExamId = exam.ExamId, PatientName = exam.PatientName, Shs = exam.Shs ?? "", ExamCode = exam.ExamCode,
                    Ready = exam.Ready, ReadinessText = exam.Ready ? "Đủ điều kiện" : "Thiếu dữ liệu", Detail = exam.Ready ? "" : string.Join(", ", errors) });
            }
            SetStatus($"Đã tải {exams.Count} hồ sơ. Hồ sơ thiếu điều kiện không thể chọn gửi.");
        }
        catch (Exception ex) { SetStatus("Không tải được hồ sơ: " + ex.Message); }
        finally { SetBusy(false); UpdateRunEnabled(); }
    }

    private Task LoadCertificatesAsync()
    {
        try
        {
            using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
            store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
            foreach (var original in store.Certificates)
            {
                try
                {
                    using var rsa = original.GetRSAPublicKey();
                    if (rsa is null || !original.HasPrivateKey || original.NotBefore > DateTime.Now || original.NotAfter < DateTime.Now) continue;
                    var copy = new X509Certificate2(original);
                    _ownedCertificates.Add(copy);
                    _certificates.Items.Add(new CertificateChoice(copy));
                }
                catch (CryptographicException) { }
            }
            if (_certificates.Items.Count > 0) _certificates.SelectedIndex = 0;
            else SetStatus("Không tìm thấy chứng thư RSA hợp lệ có khóa riêng trong CurrentUser\\My.");
        }
        catch (Exception ex) { SetStatus("Không đọc được Windows Certificate Store: " + ex.Message); }
        return Task.CompletedTask;
    }

    private async Task RunBatchAsync()
    {
        if (string.IsNullOrWhiteSpace(_settings.BatchApiKey))
        {
            MessageBox.Show(this, "Cấu hình KSK_BATCH_API_KEY ở API server và nhập cùng khóa trong Thiết lập → Cấu hình API.", "Thiếu khóa batch", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (_certificates.SelectedItem is not CertificateChoice certificate || _campaigns.SelectedItem is not CampaignDto campaign || _companies.SelectedItem is not CompanyDto company) return;
        var selected = _rows.Where(row => row.Selected && row.Ready).ToList();
        if (selected.Count == 0) { MessageBox.Show(this, "Hãy chọn ít nhất một hồ sơ đủ điều kiện."); return; }
        if (MessageBox.Show(this, $"Tạo batch và tuần tự ký/gửi {selected.Count} hồ sơ lên HSSK Hà Nội? PIN Token có thể được yêu cầu trong quá trình ký.", "Xác nhận gửi batch", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;

        SetBusy(true, "Đang tạo batch theo dõi…");
        try
        {
            var batch = await SendAsync<BatchDto>("lien-thong/batches", HttpMethod.Post,
                new { company_id = company.CompanyId, campaign_id = campaign.CampaignId, exam_ids = selected.Select(x => x.ExamId).ToArray() }, batchAuth: true);
            var itemsByExam = batch.Items.ToDictionary(x => x.ExamId);
            foreach (var row in selected)
            {
                if (!itemsByExam.TryGetValue(row.ExamId, out var item)) continue;
                if (item.Status == "NotReady") { row.State = item.Status; row.Detail = item.LastError ?? "Không đủ điều kiện."; continue; }
                await ProcessOneAsync(batch.BatchId, item, row, certificate.Certificate, campaign.CampaignId);
                _grid.Refresh();
            }
            SetStatus($"Batch #{batch.BatchId} hoàn tất xử lý. Kiểm tra trạng thái và phản hồi từng hồ sơ trong danh sách.");
        }
        catch (Exception ex) { SetStatus("Batch dừng: " + ex.Message); }
        finally { SetBusy(false); _grid.Refresh(); }
    }

    private async Task ShowBatchHistoryAsync()
    {
        if (string.IsNullOrWhiteSpace(_settings.BatchApiKey))
        {
            MessageBox.Show(this, "Nhập API key trong Thiết lập → Cấu hình API trước.", "Thiếu khóa batch", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        try
        {
            var batches = await SendAsync<List<BatchDto>>("lien-thong/batches?limit=100", HttpMethod.Get, null, batchAuth: true);
            var dialog = new Form { Text = "Nhật ký liên thông batch", Width = 1100, Height = 650, StartPosition = FormStartPosition.CenterParent };
            var grid = new DataGridView { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill, SelectionMode = DataGridViewSelectionMode.FullRowSelect };
            grid.Columns.Add("BatchId", "Batch"); grid.Columns.Add("CreatedAt", "Thời điểm tạo"); grid.Columns.Add("CampaignId", "Đợt khám");
            grid.Columns.Add("ExamId", "ExamId"); grid.Columns.Add("State", "Trạng thái"); grid.Columns.Add("MessageId", "Message ID");
            grid.Columns.Add("Transaction", "Mã giao dịch"); grid.Columns.Add("Error", "Lỗi / phản hồi");
            var detail = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, WordWrap = false };
            var retry = new Button { Text = "Tạo batch mới cho hồ sơ Failed", AutoSize = true, Enabled = false };
            retry.Click += async (_, _) => { if (grid.CurrentRow?.Tag is BatchDto selectedBatch) await RetryFailedAsync(selectedBatch); };
            foreach (var batch in batches)
                foreach (var item in batch.Items)
                {
                    var index = grid.Rows.Add(batch.BatchId, batch.CreatedAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss"), batch.CampaignId,
                        item.ExamId, item.Status, item.MessageId, item.TransactionCode, item.LastError);
                    grid.Rows[index].Tag = batch;
                }
            grid.SelectionChanged += (_, _) => detail.Text = grid.CurrentRow?.Tag as string ?? "Không có response được lưu cho hồ sơ này.";
            grid.SelectionChanged += (_, _) =>
            {
                var batch = grid.CurrentRow?.Tag as BatchDto;
                var examId = long.TryParse(grid.CurrentRow?.Cells[3].Value?.ToString(), out var id) ? id : 0;
                var item = batch?.Items.FirstOrDefault(i => i.ExamId == examId);
                detail.Text = item?.ResponsePayload ?? item?.LastError ?? "Không có response được lưu cho hồ sơ này.";
                retry.Enabled = batch is not null && item?.Status == "Failed";
            };
            var split = new SplitContainer { Dock = DockStyle.Fill, Orientation = Orientation.Horizontal, SplitterDistance = 410 };
            split.Panel1.Controls.Add(grid);
            var lower = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1 };
            lower.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); lower.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            lower.Controls.Add(detail, 0, 0); lower.Controls.Add(retry, 0, 1);
            split.Panel2.Controls.Add(lower); dialog.Controls.Add(split);
            if (grid.Rows.Count > 0) grid.Rows[0].Selected = true;
            dialog.ShowDialog(this); dialog.Dispose();
        }
        catch (Exception ex) { SetStatus("Không tải được nhật ký batch: " + ex.Message); }
    }

    private async Task RetryFailedAsync(BatchDto oldBatch)
    {
        var failed = oldBatch.Items.Where(item => item.Status == "Failed").Select(item => item.ExamId).ToArray();
        if (failed.Length == 0 || _certificates.SelectedItem is not CertificateChoice certificate) return;
        if (MessageBox.Show(this, $"Tạo batch mới để thử lại {failed.Length} hồ sơ đang Failed? Success/Rejected/Uncertain không bị gửi lại.",
            "Xác nhận thử lại", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        try
        {
            var batch = await SendAsync<BatchDto>("lien-thong/batches", HttpMethod.Post,
                new { company_id = oldBatch.CompanyId, campaign_id = oldBatch.CampaignId, exam_ids = failed }, batchAuth: true);
            var byExam = batch.Items.ToDictionary(item => item.ExamId);
            foreach (var examId in failed)
            {
                if (!byExam.TryGetValue(examId, out var item) || item.Status == "NotReady") continue;
                var row = _rows.FirstOrDefault(x => x.ExamId == examId) ?? new BatchExamRow { ExamId = examId, ExamCode = examId.ToString(), Ready = true };
                if (!_rows.Contains(row)) _rows.Add(row);
                await ProcessOneAsync(batch.BatchId, item, row, certificate.Certificate, batch.CampaignId);
                _grid.Refresh();
            }
            SetStatus($"Đã xử lý batch thử lại #{batch.BatchId}. Hồ sơ Uncertain không tự gửi lại; cần đối soát cổng.");
        }
        catch (Exception ex) { SetStatus("Không thử lại được batch: " + ex.Message); }
    }

    private async Task ProcessOneAsync(long batchId, BatchItemDto item, BatchExamRow row, X509Certificate2 certificate, long campaignId)
    {
        string? xmlHash = null;
        var pushStarted = false;
        try
        {
            row.State = "Tạo XML"; row.Detail = "Đang lấy XML từ API…"; _grid.Refresh();
            var preview = await GetAsync<XmlPreviewDto>($"exams/{row.ExamId}/lien-thong/xml-preview?campaign_id={campaignId}");
            if (!preview.Ready) throw new InvalidOperationException("Hồ sơ không còn đủ điều kiện; cần kiểm tra lại dữ liệu.");
            var xmlBytes = Encoding.UTF8.GetBytes(preview.Xml);
            xmlHash = Convert.ToHexString(SHA256.HashData(xmlBytes));
            await UpdateItemAsync(batchId, item.BatchItemId, new { status = "Signing", xml_sha256 = xmlHash, last_error = (string?)null });

            row.State = "Ký số"; row.Detail = "Đang ký XML bằng Windows CSP/KSP…"; _grid.Refresh();
            var signature = SignXml(certificate, preview.Xml);
            if (!VerifyXmlSignature(certificate, preview.Xml, signature))
                throw new CryptographicException("Chữ ký vừa tạo không xác minh được trên đúng nội dung XML; đã dừng trước khi gửi.");
            await UpdateItemAsync(batchId, item.BatchItemId, new { status = "Signed", xml_sha256 = xmlHash, last_error = (string?)null });

            var envelope = await SendAsync<JsonElement>("lien-thong/prepare", HttpMethod.Post,
                new { raw_data = preview.Xml, data_type = "xml/base64", signature });
            var messageId = envelope.GetProperty("header").GetProperty("msg_id").GetString();
            await UpdateItemAsync(batchId, item.BatchItemId, new { status = "Sending", xml_sha256 = xmlHash, message_id = messageId, last_error = (string?)null });
            row.State = "Đang gửi"; row.Detail = "Đang gửi request riêng cho hồ sơ…"; _grid.Refresh();

            pushStarted = true;
            using var response = await SendRawAsync("lien-thong/push-envelope", HttpMethod.Post, envelope, batchAuth: false);
            var raw = await response.Content.ReadAsStringAsync();
            var parsed = JsonDocument.Parse(raw);
            var tx = FindString(parsed.RootElement, ["maGiaoDich", "ma_giao_dich", "transaction_code", "transaction_id", "transactionId"]);
            var remoteStatus = GetRemoteStatusCode(parsed.RootElement);
            var externalSuccess = response.IsSuccessStatusCode && remoteStatus is >= 200 and < 300 && !HasExplicitFailure(parsed.RootElement);
            var uncertain = (int)response.StatusCode >= 500 || remoteStatus is >= 500;
            var finalState = externalSuccess ? "Success" : uncertain ? "Uncertain" : "Rejected";
            await UpdateItemAsync(batchId, item.BatchItemId, new { status = finalState, xml_sha256 = xmlHash,
                message_id = messageId, transaction_code = tx, response_payload = Limit(raw, 200000), last_error = externalSuccess ? null : Limit(raw, 2000) });
            row.State = finalState; row.Detail = tx is null ? Limit(raw, 1500) : $"Mã giao dịch: {tx} · {Limit(raw, 1200)}";
        }
        catch (Exception ex)
        {
            var state = pushStarted && (ex is not HttpRequestException httpError || httpError.StatusCode is null || (int)httpError.StatusCode >= 500) ? "Uncertain" : "Failed";
            row.State = state; row.Detail = ex.Message;
            try { await UpdateItemAsync(batchId, item.BatchItemId, new { status = state, xml_sha256 = xmlHash, last_error = Limit(ex.Message, 2000) }); }
            catch { row.Detail += " (không ghi được trạng thái lên API; cần đối soát trước khi gửi lại)"; }
        }
    }

    private async Task UpdateItemAsync(long batchId, long itemId, object body) =>
        _ = await SendAsync<JsonElement>($"lien-thong/batches/{batchId}/items/{itemId}", HttpMethod.Patch, body, batchAuth: true);

    private async Task<T> GetAsync<T>(string path) => await SendAsync<T>(path, HttpMethod.Get, null);

    private async Task<T> SendAsync<T>(string path, HttpMethod method, object? body, bool batchAuth = false)
    {
        using var response = await SendRawAsync(path, method, body, batchAuth);
        var content = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode) throw MakeHttpException(response.StatusCode, content);
        return JsonSerializer.Deserialize<T>(content, JsonOptions) ?? throw new InvalidOperationException("API trả về JSON rỗng.");
    }

    private async Task<HttpResponseMessage> SendRawAsync(string path, HttpMethod method, object? body, bool batchAuth)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null) request.Content = new StringContent(body is JsonElement element ? element.GetRawText() : JsonSerializer.Serialize(body, JsonOptions), Encoding.UTF8, "application/json");
        if (batchAuth) request.Headers.Add("X-KSK-Batch-Key", _settings.BatchApiKey);
        return await _http.SendAsync(request);
    }

    private static HttpRequestException MakeHttpException(HttpStatusCode status, string body) => new($"API HTTP {(int)status}: {Limit(body, 1800)}", null, status);

    private static string SignXml(X509Certificate2 certificate, string xml)
    {
        using var rsa = certificate.GetRSAPrivateKey() ?? throw new CryptographicException("Chứng thư không truy cập được khóa RSA riêng.");
        return Convert.ToBase64String(rsa.SignData(Encoding.UTF8.GetBytes(xml), HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1));
    }

    private static bool VerifyXmlSignature(X509Certificate2 certificate, string xml, string signatureBase64)
    {
        using var rsa = certificate.GetRSAPublicKey() ?? throw new CryptographicException("Chứng thư không có khóa RSA công khai.");
        return rsa.VerifyData(Encoding.UTF8.GetBytes(xml), Convert.FromBase64String(signatureBase64),
            HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
    }

    private static bool HasExplicitFailure(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object) return false;
        if (root.TryGetProperty("push", out var push)) return HasExplicitFailure(push);
        if (root.TryGetProperty("body", out var body) && HasExplicitFailure(body)) return true;
        if (root.TryGetProperty("header", out var header) && header.ValueKind == JsonValueKind.Object && header.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.False) return true;
        return root.TryGetProperty("success", out var flag) && flag.ValueKind == JsonValueKind.False;
    }

    private static int? GetRemoteStatusCode(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object) return null;
        if (root.TryGetProperty("push", out var push) && push.ValueKind == JsonValueKind.Object && push.TryGetProperty("status_code", out var status) && status.TryGetInt32(out var code)) return code;
        return null;
    }

    private static string? FindString(JsonElement element, string[] candidates)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                if (candidates.Contains(property.Name, StringComparer.OrdinalIgnoreCase) && property.Value.ValueKind == JsonValueKind.String) return property.Value.GetString();
                var nested = FindString(property.Value, candidates); if (nested is not null) return nested;
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
            foreach (var child in element.EnumerateArray()) { var nested = FindString(child, candidates); if (nested is not null) return nested; }
        return null;
    }

    private void UpdateRunEnabled() => _run.Enabled = !_busy && _rows.Any(row => row.Selected && row.Ready) && _certificates.SelectedItem is CertificateChoice;
    private bool _busy;
    private void SetBusy(bool busy, string? message = null) { _busy = busy; _load.Enabled = !busy; if (message is not null) SetStatus(message); UpdateRunEnabled(); }
    private void SetStatus(string message) { _status.Text = message; }
    private static string Limit(string text, int length) => text.Length <= length ? text : text[..length];

    private sealed class CertificateChoice
    {
        public CertificateChoice(X509Certificate2 certificate) => Certificate = certificate;
        public X509Certificate2 Certificate { get; }
        public override string ToString() => $"{Certificate.GetNameInfo(X509NameType.SimpleName, false)} · {Certificate.Thumbprint} · hết hạn {Certificate.NotAfter:yyyy-MM-dd}";
    }

    private sealed class BatchExamRow
    {
        public bool Selected { get; set; }
        public long ExamId { get; set; }
        public string PatientName { get; set; } = "";
        public string Shs { get; set; } = "";
        public string ExamCode { get; set; } = "";
        public bool Ready { get; set; }
        public string ReadinessText { get; set; } = "";
        public string State { get; set; } = "Chưa chạy";
        public string Detail { get; set; } = "";
    }

    private sealed class CompanyDto { [JsonPropertyName("company_id")] public long CompanyId { get; set; } [JsonPropertyName("name")] public string Name { get; set; } = ""; }
    private sealed class CampaignDto { [JsonPropertyName("campaign_id")] public long CampaignId { get; set; } [JsonPropertyName("campaign_name")] public string CampaignName { get; set; } = ""; }
    private sealed class ReadinessErrorDto { [JsonPropertyName("field_name")] public string FieldName { get; set; } = ""; }
    private sealed class ExamDto
    {
        [JsonPropertyName("exam_id")] public long ExamId { get; set; }
        [JsonPropertyName("exam_code")] public string ExamCode { get; set; } = "";
        [JsonPropertyName("patient_name")] public string PatientName { get; set; } = "";
        [JsonPropertyName("shs")] public string? Shs { get; set; }
        [JsonPropertyName("ready")] public bool Ready { get; set; }
        [JsonPropertyName("readiness_errors")] public List<ReadinessErrorDto>? ReadinessErrors { get; set; }
    }
    private sealed class XmlPreviewDto { [JsonPropertyName("xml")] public string Xml { get; set; } = ""; [JsonPropertyName("ready")] public bool Ready { get; set; } }
    private sealed class BatchDto
    {
        [JsonPropertyName("batch_id")] public long BatchId { get; set; }
        [JsonPropertyName("company_id")] public long CompanyId { get; set; }
        [JsonPropertyName("campaign_id")] public long CampaignId { get; set; }
        [JsonPropertyName("status")] public string Status { get; set; } = "";
        [JsonPropertyName("created_at")] public DateTime CreatedAt { get; set; }
        [JsonPropertyName("items")] public List<BatchItemDto> Items { get; set; } = [];
    }
    private sealed class BatchItemDto
    {
        [JsonPropertyName("batch_item_id")] public long BatchItemId { get; set; }
        [JsonPropertyName("exam_id")] public long ExamId { get; set; }
        [JsonPropertyName("status")] public string Status { get; set; } = "";
        [JsonPropertyName("last_error")] public string? LastError { get; set; }
        [JsonPropertyName("message_id")] public string? MessageId { get; set; }
        [JsonPropertyName("transaction_code")] public string? TransactionCode { get; set; }
        [JsonPropertyName("response_payload")] public string? ResponsePayload { get; set; }
    }
}
