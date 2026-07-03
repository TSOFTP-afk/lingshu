const { app, BrowserWindow } = require('electron');
const fs = require('fs');

const url = process.argv[2];
const outputPath = process.argv[3];
const width = Number(process.argv[4] || 1440);
const height = Number(process.argv[5] || 900);

if (!url || !outputPath) {
  console.error('Usage: electron tools/capture_url_screenshot.js <url> <output.png> [width] [height]');
  process.exit(2);
}

const events = [];

async function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width,
    height,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  });

  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    events.push({ type: 'console', level, message, line, sourceId });
  });
  win.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    events.push({ type: 'did-fail-load', errorCode, errorDescription, validatedURL });
  });
  win.webContents.on('render-process-gone', (_event, details) => {
    events.push({ type: 'render-process-gone', details });
  });

  try {
    await win.loadURL(url);
    await wait(3000);
    const image = await win.webContents.capturePage();
    fs.writeFileSync(outputPath, image.toPNG());
    fs.writeFileSync(`${outputPath}.json`, JSON.stringify(events, null, 2));
  } catch (err) {
    events.push({ type: 'capture-error', message: err && err.stack ? err.stack : String(err) });
    fs.writeFileSync(`${outputPath}.json`, JSON.stringify(events, null, 2));
    process.exitCode = 1;
  } finally {
    win.destroy();
    app.quit();
  }
});
