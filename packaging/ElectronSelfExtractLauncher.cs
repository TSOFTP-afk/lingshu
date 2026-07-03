using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

namespace LingShuElectronLauncher
{
    internal static class Program
    {
        [STAThread]
        private static int Main()
        {
            LauncherSplash splash = null;
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                if (string.IsNullOrEmpty(exeDir))
                {
                    exeDir = Environment.CurrentDirectory;
                }

                string runtimeBase = ResolveRuntimeBase(exeDir);
                string installDir = EnsureInstallDir(Path.Combine(runtimeBase, "versions"), SafeVersionName(LauncherConfig.Version));
                string stampPath = Path.Combine(installDir, ".lingshu-extracted");
                string innerExe = Path.Combine(installDir, LauncherConfig.InnerExeName);
                string expectedStamp = BuildPayloadStamp();

                if (NeedsExtract(stampPath, expectedStamp, innerExe))
                {
                    splash = new LauncherSplash(LauncherConfig.AppName);
                    splash.Show();
                    splash.SetStage("正在准备 " + LauncherConfig.AppName, "首次启动需要展开本地运行文件");
                    Application.DoEvents();

                    DeleteDir(installDir);
                    Directory.CreateDirectory(installDir);
                    ExtractPayload(installDir, splash);
                    File.WriteAllText(stampPath, expectedStamp);
                    splash.SetStage("准备完成", "以后将直接复用本地运行文件");
                    splash.PumpDelay(260);
                }

                if (Environment.GetEnvironmentVariable("LINGSHU_LAUNCHER_EXTRACT_ONLY") == "1")
                {
                    return 0;
                }

                if (!File.Exists(innerExe))
                {
                    throw new FileNotFoundException("Application executable was not extracted: " + innerExe);
                }

                string dataDir = Path.Combine(exeDir, "data");
                Directory.CreateDirectory(dataDir);

                ProcessStartInfo startInfo = new ProcessStartInfo();
                startInfo.FileName = innerExe;
                startInfo.WorkingDirectory = installDir;
                startInfo.UseShellExecute = false;
                startInfo.EnvironmentVariables["LINGSHU_LAUNCHER_EXE"] = Assembly.GetExecutingAssembly().Location;
                startInfo.EnvironmentVariables["LINGSHU_PORTABLE_ROOT"] = exeDir;
                startInfo.EnvironmentVariables["LINGSHU_PORTABLE_RUNTIME_DIR"] = installDir;
                startInfo.EnvironmentVariables["LINGSHU_PORTABLE_DATA_DIR"] = dataDir;
                Process.Start(startInfo);
                return 0;
            }
            catch (Exception exc)
            {
                try { Console.Error.WriteLine(exc.ToString()); } catch { }
                MessageBox.Show(
                    exc.Message,
                    LauncherConfig.AppName + " startup failed",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }
            finally
            {
                if (splash != null)
                {
                    splash.CloseSplash();
                }
            }
        }

        private static string ResolveRuntimeBase(string exeDir)
        {
            string portableBase = Path.Combine(exeDir, ".lingshu-runtime");
            if (CanUseDirectory(portableBase))
            {
                TrySetHidden(portableBase);
                return portableBase;
            }

            string localBase = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                LauncherConfig.AppName,
                ".lingshu-runtime"
            );
            Directory.CreateDirectory(localBase);
            return localBase;
        }

        private static bool CanUseDirectory(string dir)
        {
            try
            {
                Directory.CreateDirectory(dir);
                string probe = Path.Combine(dir, ".write-test-" + Guid.NewGuid().ToString("N"));
                File.WriteAllText(probe, "ok");
                File.Delete(probe);
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static void TrySetHidden(string dir)
        {
            try
            {
                DirectoryInfo info = new DirectoryInfo(dir);
                info.Attributes = info.Attributes | FileAttributes.Hidden;
            }
            catch { }
        }

        private static string SafeVersionName(string version)
        {
            foreach (char c in Path.GetInvalidFileNameChars())
            {
                version = version.Replace(c, '_');
            }
            return version;
        }

        private static string EnsureInstallDir(string parentDir, string baseName)
        {
            Directory.CreateDirectory(parentDir);
            string dir = Path.Combine(parentDir, baseName);
            Directory.CreateDirectory(dir);
            return dir;
        }

        private static string BuildPayloadStamp()
        {
            string exePath = Assembly.GetExecutingAssembly().Location;
            FileInfo fileInfo = new FileInfo(exePath);
            return LauncherConfig.Version + "|" + fileInfo.Length + "|" + fileInfo.LastWriteTimeUtc.Ticks;
        }

        private static bool NeedsExtract(string stampPath, string expectedStamp, string innerExe)
        {
            if (!File.Exists(innerExe))
            {
                return true;
            }
            try
            {
                return !File.Exists(stampPath) || File.ReadAllText(stampPath) != expectedStamp;
            }
            catch
            {
                return true;
            }
        }

        private static void DeleteDir(string path)
        {
            try
            {
                if (Directory.Exists(path))
                {
                    Directory.Delete(path, true);
                }
            }
            catch
            {
                try
                {
                    string backup = path + "_old_" + Guid.NewGuid().ToString("N").Substring(0, 8);
                    Directory.Move(path, backup);
                }
                catch { }
            }
        }

        private static void ExtractPayload(string installDir, LauncherSplash splash)
        {
            using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            {
                if (source == null)
                {
                    throw new InvalidOperationException("Embedded payload.zip was not found.");
                }
                using (ZipArchive archive = new ZipArchive(source, ZipArchiveMode.Read))
                {
                    int total = archive.Entries.Count;
                    int current = 0;
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        current += 1;
                        ExtractEntry(entry, installDir);
                        if (current % 12 == 0 || current == total)
                        {
                            splash.SetProgress(total == 0 ? 0 : (int)((current * 100.0) / total));
                            splash.SetStage("正在展开运行文件", current + " / " + total);
                            splash.Pump();
                        }
                    }
                }
            }
        }

        private static void ExtractEntry(ZipArchiveEntry entry, string installDir)
        {
            string relativePath = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
            if (string.IsNullOrWhiteSpace(relativePath)) return;

            string destination = Path.GetFullPath(Path.Combine(installDir, relativePath));
            string root = Path.GetFullPath(installDir + Path.DirectorySeparatorChar);
            if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Blocked unsafe payload path: " + entry.FullName);
            }

            if (string.IsNullOrEmpty(entry.Name))
            {
                Directory.CreateDirectory(destination);
                return;
            }

            string parent = Path.GetDirectoryName(destination);
            if (!string.IsNullOrEmpty(parent))
            {
                Directory.CreateDirectory(parent);
            }

            using (Stream input = entry.Open())
            using (FileStream output = new FileStream(destination, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                input.CopyTo(output);
            }
        }
    }

    internal sealed class LauncherSplash : Form
    {
        private readonly Label titleLabel;
        private readonly Label stageLabel;
        private readonly Label detailLabel;
        private readonly ProgressBar progressBar;

        public LauncherSplash(string appName)
        {
            Text = appName;
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.None;
            Width = 560;
            Height = 310;
            BackColor = Color.FromArgb(11, 18, 32);
            ShowInTaskbar = true;
            DoubleBuffered = true;

            titleLabel = new Label();
            titleLabel.Text = appName;
            titleLabel.ForeColor = Color.White;
            titleLabel.BackColor = Color.Transparent;
            titleLabel.Font = new Font("Microsoft YaHei UI", 24, FontStyle.Bold);
            titleLabel.AutoSize = false;
            titleLabel.SetBounds(42, 46, 420, 48);
            Controls.Add(titleLabel);

            stageLabel = new Label();
            stageLabel.ForeColor = Color.FromArgb(222, 245, 244);
            stageLabel.BackColor = Color.Transparent;
            stageLabel.Font = new Font("Microsoft YaHei UI", 12, FontStyle.Bold);
            stageLabel.AutoSize = false;
            stageLabel.SetBounds(46, 150, 460, 28);
            Controls.Add(stageLabel);

            detailLabel = new Label();
            detailLabel.ForeColor = Color.FromArgb(154, 172, 194);
            detailLabel.BackColor = Color.Transparent;
            detailLabel.Font = new Font("Microsoft YaHei UI", 10, FontStyle.Regular);
            detailLabel.AutoSize = false;
            detailLabel.SetBounds(46, 181, 460, 24);
            Controls.Add(detailLabel);

            progressBar = new ProgressBar();
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Minimum = 0;
            progressBar.Maximum = 100;
            progressBar.Value = 0;
            progressBar.SetBounds(46, 232, 468, 8);
            Controls.Add(progressBar);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Rectangle rect = ClientRectangle;
            using (LinearGradientBrush brush = new LinearGradientBrush(
                rect,
                Color.FromArgb(10, 18, 34),
                Color.FromArgb(14, 84, 91),
                135f))
            {
                e.Graphics.FillRectangle(brush, rect);
            }

            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (SolidBrush markBrush = new SolidBrush(Color.FromArgb(23, 181, 168)))
            {
                e.Graphics.FillRoundedRectangle(markBrush, new Rectangle(456, 42, 58, 58), 14);
            }
            using (Font markFont = new Font("Microsoft YaHei UI", 24, FontStyle.Bold))
            using (SolidBrush textBrush = new SolidBrush(Color.White))
            {
                e.Graphics.DrawString("灵", markFont, textBrush, new PointF(467, 51));
            }
        }

        public void SetStage(string stage, string detail)
        {
            stageLabel.Text = stage;
            detailLabel.Text = detail;
            Pump();
        }

        public void SetProgress(int value)
        {
            if (value < 0) value = 0;
            if (value > 100) value = 100;
            progressBar.Value = value;
        }

        public void Pump()
        {
            try
            {
                Application.DoEvents();
            }
            catch { }
        }

        public void PumpDelay(int milliseconds)
        {
            DateTime until = DateTime.Now.AddMilliseconds(milliseconds);
            while (DateTime.Now < until)
            {
                Pump();
                Thread.Sleep(20);
            }
        }

        public void CloseSplash()
        {
            try
            {
                Close();
                Dispose();
            }
            catch { }
        }
    }

    internal static class GraphicsExtensions
    {
        public static void FillRoundedRectangle(this Graphics graphics, Brush brush, Rectangle bounds, int radius)
        {
            using (GraphicsPath path = RoundedRectangle(bounds, radius))
            {
                graphics.FillPath(brush, path);
            }
        }

        private static GraphicsPath RoundedRectangle(Rectangle bounds, int radius)
        {
            int diameter = radius * 2;
            GraphicsPath path = new GraphicsPath();
            path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }
    }
}
