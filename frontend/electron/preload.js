const apiArg = process.argv.find((arg) => arg.startsWith("--desktop-api-base="));
const apiBase = apiArg ? apiArg.split("=").slice(1).join("=") : "http://127.0.0.1:8084/api";

window.desktopAppConfig = {
  ...(window.desktopAppConfig || {}),
  apiBase,
  platform: process.platform,
  desktop: true,
};
