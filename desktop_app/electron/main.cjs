const { app, BrowserWindow, ipcMain, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const apiBase = process.env.DESKTOP_API_BASE || "http://127.0.0.1:8084/api";
const paymentSiteUrl = process.env.PAYMENT_SITE_URL || "http://localhost:3001";
const isDev = !app.isPackaged;

if (process.platform === "linux") {
  app.commandLine.appendSwitch("no-sandbox");
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-software-rasterizer");
  app.disableHardwareAcceleration();
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1320,
    height: 880,
    minWidth: 1060,
    minHeight: 720,
    title: "Modular Shorts Studio",
    backgroundColor: "#f6f7f3",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
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

  const indexPath = path.join(__dirname, "..", "dist", "index.html");
  if (fs.existsSync(indexPath)) {
    win.loadFile(indexPath);
  } else {
    win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(missingBuildHtml(indexPath))}`);
  }
}

function missingBuildHtml(indexPath) {
  return `<!doctype html><html><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#111;color:#fff;font-family:sans-serif"><main style="max-width:680px;padding:28px"><h1>Desktop UI build is missing</h1><p>Run npm run build inside desktop_app before starting Electron.</p><code>${escapeHtml(indexPath)}</code></main></body></html>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

ipcMain.handle("desktop:config", () => ({ apiBase, paymentSiteUrl }));

ipcMain.handle("desktop:open-payment-site", (_event, suffix = "") => {
  const target = new URL(paymentSiteUrl);
  const cleanSuffix = String(suffix || "");
  if (cleanSuffix.startsWith("?")) {
    target.search = cleanSuffix;
  } else if (cleanSuffix.startsWith("/")) {
    target.pathname = cleanSuffix;
  }
  return shell.openExternal(target.toString());
});

app.whenReady().then(() => {
  app.setAppUserModelId("com.modularshorts.paiddesktop");
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
