#!/bin/sh
# Zip the extension for the app's install page (frontend/public). Run this
# after changing anything in extension/, and commit the zip.
set -e
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
mkdir "$tmp/job-hunt-extension"
cp extension/manifest.json extension/*.js "$tmp/job-hunt-extension/"
cp -R extension/icons "$tmp/job-hunt-extension/"
rm -f frontend/public/job-hunt-extension.zip
(cd "$tmp" && zip -qrX job-hunt-extension.zip job-hunt-extension)
mv "$tmp/job-hunt-extension.zip" frontend/public/job-hunt-extension.zip
rm -rf "$tmp"
echo "frontend/public/job-hunt-extension.zip"
