const fs = require("fs");
const path = require("path");

const frontendRoot = path.join(__dirname, "..");
const sourceDir = path.join(frontendRoot, "..", "playground", "ui", "dist");
const targetDir = path.join(frontendRoot, "dist");
const sourceIndex = path.join(sourceDir, "index.html");

if (!fs.existsSync(sourceIndex)) {
  throw new Error(`Desktop UI source is missing: ${sourceIndex}`);
}

fs.rmSync(targetDir, { recursive: true, force: true });
fs.cpSync(sourceDir, targetDir, { recursive: true });
console.log(`Prepared desktop UI: ${targetDir}`);
