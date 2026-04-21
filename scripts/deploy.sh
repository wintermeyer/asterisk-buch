#!/usr/bin/env bash
set -euo pipefail

# Deploy script intended for a self-hosted Antora runner.
# Mirrors the ruby-book deployment pattern: atomic symlink swap under
# /var/www/asterisk-buch/releases/<timestamp>/, served at /asterisk/book/.

# Activate mise so node / npm / npx resolve on the non-interactive shell
# GitHub Actions spawns. `mise activate` only wires the shim dir via a
# precmd hook that never fires here, so prepend the shim dir to PATH
# directly.
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
elif [ -x "$HOME/.local/bin/mise" ]; then
  eval "$("$HOME/.local/bin/mise" activate bash)"
fi
export PATH="${HOME}/.local/share/mise/shims:${PATH}"

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
