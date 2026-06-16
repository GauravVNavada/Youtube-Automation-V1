#!/usr/bin/env bash
set -euo pipefail

npm run desktop:pack:win

cd release
zip -r "Modular Shorts Studio-0.1.0-windows-x64.zip" win-unpacked

echo "Created release/Modular Shorts Studio-0.1.0-windows-x64.zip"
