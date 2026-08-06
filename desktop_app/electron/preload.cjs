const { contextBridge, ipcRenderer } = require("electron");

const TOKEN_KEY = "modular-shorts-desktop-token";
let configPromise;

function config() {
  if (!configPromise) configPromise = ipcRenderer.invoke("desktop:config");
  return configPromise;
}

async function request(path, options = {}) {
  const appConfig = await config();
  const headers = new Headers(options.headers || {});
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${appConfig.apiBase}${path}`, {
    method: options.method || "GET",
    headers,
    body
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(typeof payload.detail === "string" ? payload.detail : `Request failed with ${response.status}`);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

contextBridge.exposeInMainWorld("desktopApi", {
  config,
  request,
  openPaymentSite: (suffix = "") => ipcRenderer.invoke("desktop:open-payment-site", suffix),
  token: {
    get: () => localStorage.getItem(TOKEN_KEY) || "",
    set: (value) => localStorage.setItem(TOKEN_KEY, value || ""),
    clear: () => localStorage.removeItem(TOKEN_KEY)
  }
});
