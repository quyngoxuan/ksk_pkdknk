using System.Security.Cryptography;
using System.Text;

namespace KskLienthong;

internal sealed record AppSettings(string ApiBaseUrl, string XmlOutputDirectory, string XmlFileNamePattern, string BatchApiKey)
{
    public string ApiOrigin => new Uri(ApiBaseUrl).GetLeftPart(UriPartial.Authority).ToLowerInvariant();

    public static string IniPath => Path.Combine(AppContext.BaseDirectory, "ini.txt");

    public static AppSettings Default => new(
        "http://localhost:5500",
        Path.Combine(AppContext.BaseDirectory, "XML"),
        "KSK_{examId}.xml",
        "");

    public static AppSettings Load()
    {
        if (!File.Exists(IniPath)) return Default;
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in File.ReadLines(IniPath))
        {
            var trimmed = line.Trim();
            if (trimmed.Length == 0 || trimmed.StartsWith(';') || trimmed.StartsWith('#')) continue;
            var separator = trimmed.IndexOf('=');
            if (separator <= 0) continue;
            values[trimmed[..separator].Trim()] = trimmed[(separator + 1)..].Trim();
        }
        var defaults = Default;
        var protectedKey = values.GetValueOrDefault("BATCH_API_KEY_PROTECTED", "");
        var batchApiKey = "";
        if (!string.IsNullOrWhiteSpace(protectedKey))
        {
            try
            {
                batchApiKey = Encoding.UTF8.GetString(ProtectedData.Unprotect(
                    Convert.FromBase64String(protectedKey), null, DataProtectionScope.CurrentUser));
            }
            catch (CryptographicException) { }
            catch (FormatException) { }
        }
        return new AppSettings(
            values.GetValueOrDefault("API_BASE_URL", defaults.ApiBaseUrl),
            values.GetValueOrDefault("XML_OUTPUT_DIRECTORY", defaults.XmlOutputDirectory),
            values.GetValueOrDefault("XML_FILE_NAME_PATTERN", defaults.XmlFileNamePattern), batchApiKey);
    }

    public void Save()
    {
        var directory = Path.GetDirectoryName(IniPath)!;
        Directory.CreateDirectory(directory);
        var protectedKey = Convert.ToBase64String(ProtectedData.Protect(
            Encoding.UTF8.GetBytes(BatchApiKey), null, DataProtectionScope.CurrentUser));
        File.WriteAllText(IniPath,
            "; Cấu hình KSK Liên thông Desktop. Không lưu PIN hoặc private key tại đây.\r\n" +
            $"API_BASE_URL={ApiBaseUrl}\r\n" +
            $"XML_OUTPUT_DIRECTORY={XmlOutputDirectory}\r\n" +
            $"XML_FILE_NAME_PATTERN={XmlFileNamePattern}\r\n" +
            $"BATCH_API_KEY_PROTECTED={protectedKey}\r\n",
            new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }

    public object ToWebConfig() => new
    {
        apiBaseUrl = ApiBaseUrl,
        xmlFileNamePattern = XmlFileNamePattern
    };
}
