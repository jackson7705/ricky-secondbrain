#!/usr/bin/env bash
# Proves a Locafy email-gated lead magnet works before it ships.
#
#   verify_gate.sh <repo_dir> <slug> "<phrase only visible once unlocked>" [out_dir]
#
# Needs a finished `npm run build` in <repo_dir>. Starts `next start` with a
# throwaway LISTMONK_API_TOKEN, then checks:
#   1. anonymous request shows the EmailGate and NOT the unlocked phrase / JSON-LD
#   2. a correctly signed cookie shows the unlocked phrase
#   3. another magnet's cookie does NOT unlock this page
# and saves mobile + desktop screenshots of both states to [out_dir] so they can
# be texted to Jason. Exits non-zero on any failure. Never touches Listmonk.
set -euo pipefail

REPO=${1:?repo dir}; SLUG=${2:?slug}; MARKER=${3:?unlocked phrase}
OUT=${4:-/tmp/lead-magnet-$SLUG}
PORT=${PORT:-3418}
SECRET="verify-gate-$RANDOM$RANDOM"
mkdir -p "$OUT"
cd "$REPO"

LISTMONK_API_TOKEN=$SECRET npx next start -p "$PORT" >"$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do curl -s -o /dev/null "localhost:$PORT/$SLUG" && break; sleep 1; done

URL="http://localhost:$PORT/$SLUG"
fail() { echo "FAIL: $*"; exit 1; }

# Same format as src/lib/lead-magnet-access.ts: <slug>:<expires>:<hmac>
sign() {
  local payload="$1:$(( $(date +%s) + 3600 ))"
  local sig
  sig=$(printf '%s' "lead-magnet-access:v1:$payload" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $NF}')
  echo "$payload:$sig"
}
TOKEN=$(sign "$SLUG")

anon=$(curl -s "$URL")
grep -q "Free, instant access" <<<"$anon" || fail "anonymous page has no EmailGate (is the route 200?)"
grep -qF "$MARKER" <<<"$anon" && fail "anonymous page LEAKS the unlocked phrase"
grep -q '"@type":"FAQPage"\|ItemList' <<<"$anon" && fail "anonymous page leaks JSON-LD"
echo "ok  anonymous: gate only, no content"

full=$(curl -s -b "locafy_magnet_$SLUG=$TOKEN" "$URL")
grep -qF "$MARKER" <<<"$full" || fail "signed cookie did not unlock the page"
echo "ok  signed cookie unlocks"

other=$(curl -s -b "locafy_magnet_ai-seo-checklist=$(sign ai-seo-checklist)" "$URL")
grep -qF "$MARKER" <<<"$other" && fail "another magnet's cookie unlocks this page"
echo "ok  other magnets' cookies rejected"

free=$(curl -s "localhost:$PORT/free-tools")
grep -q "href=\"/$SLUG\"" <<<"$free" || fail "/free-tools has no card linking /$SLUG"
echo "ok  listed on /free-tools"

node - "$URL" "$SLUG" "$TOKEN" "$OUT" <<'JS'
const puppeteer = require("puppeteer-core");
const [url, slug, token, out] = process.argv.slice(2);
(async () => {
  const browser = await puppeteer.launch({
    executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    headless: true,
  });
  const page = await browser.newPage();
  const shots = [["mobile", 390, 844], ["desktop", 1440, 900]];
  for (const state of ["locked", "unlocked"]) {
    if (state === "unlocked") {
      await page.setCookie({ name: `locafy_magnet_${slug}`, value: token, url });
    }
    for (const [name, width, height] of shots) {
      await page.setViewport({ width, height });
      await page.goto(url, { waitUntil: "networkidle0" });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 0) { console.log(`FAIL: ${state} ${name} scrolls sideways by ${overflow}px`); process.exitCode = 1; }
      await page.screenshot({ path: `${out}/${state}-${name}.png`, fullPage: false });
    }
  }
  await browser.close();
})();
JS
echo "ok  screenshots in $OUT"
ls "$OUT"/*.png
