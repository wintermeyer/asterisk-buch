#!/usr/bin/env bash
set -euo pipefail

# Deploy script intended for a self-hosted Antora runner.
# Mirrors the ruby-book deployment pattern: atomic symlink swap under
# /var/www/asterisk-buch/releases/<timestamp>/, served at /asterisk/book/.

cd "$(dirname "$0")/.."

npm install
npx antora --fetch antora-playbook.yml

TS="$(date +%Y%m%d%H%M%S)"
RELEASES="/var/www/asterisk-buch/releases"
TARGET="${RELEASES}/${TS}"
LINK="/var/www/asterisk-buch/current"

mkdir -p "${TARGET}"
cp -r build/site/. "${TARGET}/"

ln -sfn "${TARGET}" "${LINK}.new"
mv -Tf "${LINK}.new" "${LINK}"

# Keep the last five releases only.
ls -1dt "${RELEASES}"/*/ 2>/dev/null | tail -n +6 | xargs -r rm -rf
