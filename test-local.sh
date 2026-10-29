#!/usr/bin/env bash
# Smoke test for converter-cloud. Needs a Docker daemon.
# Builds the image, starts it, and converts a sample docx -> pdf via curl.
set -euo pipefail

if ! docker info >/dev/null 2>&1; then
  echo "NOTE: Docker daemon is not available on this machine — skipping local test."
  echo "Run this script on any machine with Docker:  bash test-local.sh"
  exit 0
fi

IMG=converter-cloud:test
echo "== building $IMG (takes a few minutes first time: LibreOffice layer) =="
docker build -t "$IMG" .

CID=$(docker run -d -p 7860:7860 "$IMG")
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT

echo "== waiting for /healthz =="
for _ in $(seq 1 40); do
  sleep 3
  if curl -sf http://127.0.0.1:7860/healthz >/dev/null 2>&1; then break; fi
done
curl -sf http://127.0.0.1:7860/healthz
echo "   healthz OK"

echo "== making a minimal sample.docx (pure python, no extra deps) =="
python3 - <<'EOF'
import zipfile
ct = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
doc = '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Hello from the converter-cloud smoke test.</w:t></w:r></w:p></w:body></w:document>'''
with zipfile.ZipFile('/tmp/sample.docx', 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml', ct)
    z.writestr('_rels/.rels', rels)
    z.writestr('word/document.xml', doc)
print("sample docx written")
EOF

echo "== POST /convert (docx -> pdf) =="
curl -sf -F "file=@/tmp/sample.docx" -F "to=pdf" http://127.0.0.1:7860/convert -o /tmp/out.pdf
if head -c 4 /tmp/out.pdf | grep -q "%PDF"; then
  echo "PASS: docx -> pdf returned a real PDF ($(wc -c < /tmp/out.pdf) bytes)"
else
  echo "FAIL: output is not a PDF"; exit 1
fi

echo "== POST /convert with bad 'to' (expect 400) =="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -F "file=@/tmp/sample.docx" -F "to=exe" http://127.0.0.1:7860/convert)
[ "$CODE" = "400" ] && echo "PASS: bad target rejected (400)" || { echo "FAIL: got $CODE"; exit 1; }

echo "ALL SMOKE TESTS PASSED"
