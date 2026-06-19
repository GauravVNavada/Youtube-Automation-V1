const { app, BrowserWindow, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const isDev = !app.isPackaged;
const apiBase = process.env.DESKTOP_API_BASE || "http://127.0.0.1:8084/api";

if (process.platform === "linux") {
  app.commandLine.appendSwitch("no-sandbox");
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-software-rasterizer");
  app.disableHardwareAcceleration();
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1040,
    minHeight: 720,
    title: "Modular Shorts Studio",
    backgroundColor: "#0f1115",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      additionalArguments: [`--desktop-api-base=${apiBase}`],
    },
  });

  win.once("ready-to-show", () => {
    win.show();
    if (isDev && process.env.ELECTRON_OPEN_DEVTOOLS === "1") {
      win.webContents.openDevTools({ mode: "detach" });
    }
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  win.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    showLoadError(win, `Could not load ${validatedURL}`, `${errorCode}: ${errorDescription}`);
  });

  win.webContents.on("render-process-gone", (_event, details) => {
    showLoadError(win, "Renderer process stopped", `${details.reason || "unknown"} (${details.exitCode})`);
  });

  const indexPath = resolveIndexPath();
  if (!indexPath) {
    showLoadError(
      win,
      "Desktop UI build is missing",
      "Expected frontend/dist/index.html or playground/ui/dist/index.html. Build or copy the UI bundle before launching."
    );
    return;
  }
  win.loadFile(indexPath);
}

function resolveIndexPath() {
  const candidates = [
    path.join(__dirname, "..", "dist", "index.html"),
    path.join(__dirname, "..", "..", "playground", "ui", "dist", "index.html"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

function showLoadError(win, title, detail) {
  const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Modular Shorts Studio</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #080f1c;
        color: #f8fafc;
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      main {
        width: min(720px, calc(100vw - 48px));
        border: 1px solid #263244;
        border-radius: 8px;
        background: #101827;
        padding: 28px;
        box-shadow: 0 20px 80px rgba(0, 0, 0, 0.35);
      }
      h1 { margin: 0 0 12px; font-size: 24px; }
      p { color: #cbd5e1; line-height: 1.55; }
      code {
        display: block;
        margin-top: 16px;
        white-space: pre-wrap;
        color: #fca5a5;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>${escapeHtml(title)}</h1>
      <p>The desktop shell opened, but the renderer UI could not start.</p>
      <code>${escapeHtml(detail)}</code>
    </main>
  </body>
</html>`;
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

app.whenReady().then(() => {
  app.setAppUserModelId("com.modularshorts.studio");
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
