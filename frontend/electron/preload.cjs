const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('desktopAppConfig', {
  apiBase: process.env.DESKTOPAPP_API_BASE || 'http://localhost:8080/api',
  platform: process.platform,
});
