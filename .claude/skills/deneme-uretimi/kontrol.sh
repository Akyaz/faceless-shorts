#!/usr/bin/env bash
# Deneme çalışmalarının bitmesini bekler, videoyu indirir, metni, görsel seçimini ve dört kareyi gösterir.
# Kullanım: bash .claude/skills/deneme-uretimi/kontrol.sh <çalışma_no> [<çalışma_no> ...]
# Çıktılar: ${DENEME_DIR:-/tmp/deneme}/<çalışma_no>/ (metadata.json, short.mp4, kareler.jpg)
set -u
OUT="${DENEME_DIR:-${TMPDIR:-/tmp}/deneme}"

ffmpeg_bin() {
  if command -v ffmpeg >/dev/null; then echo ffmpeg; return; fi
  for py in python3 python; do
    "$py" -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null && return
  done
  echo ""
}
FF=$(ffmpeg_bin)

for run in "$@"; do
  # GitHub API saatlik sınırı paylaşımlı: seyrek sorgula
  until [ "$(gh run view "$run" --json status --jq .status 2>/dev/null)" = completed ]; do sleep 180; done
  echo "=== $run $(gh run view "$run" --json conclusion --jq .conclusion)"
  gh run view "$run" --log 2>/dev/null \
    | grep -E "Traceback|RuntimeError|Konu görseli|Konu fotoğrafları|Haber kapak|Yapım karesi|Vikipedi afişi|TMDB|Arka plan|atlandı|yeniden yazdırılıyor|Görsel seçimi|Konu:" \
    | grep -v "_KEY:" | sed -E 's/^.*Z //' | cut -c1-200 | head -40
  dir="$OUT/$run"; rm -rf "$dir"; mkdir -p "$dir"  # gh run download var olan dosyanın üstüne yazmıyor
  gh run download "$run" -n short -D "$dir" >/dev/null 2>&1 || { echo "Video yok (çalışma video üretmedi)"; continue; }
  meta=$(find "$dir" -name metadata.json | head -1)
  python3 - "$meta" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
d = m["description"]
cut = lambda a, b: d[d.find(a):d.find(b) if d.find(b) > 0 else None].strip() if a in d else ""
print("Başlık:", m["title"])
body = d[d.find("Videoda:"):].split("\n\n")[0] if "Videoda:" in d else ""
lines = [x for x in body.split("\n")[1:] if x.strip()]
print("\n".join(lines))
print(f"-> {sum(len(x.split()) for x in lines)} kelime, {len(lines)} paragraf")
print(cut("Kaynaklar:", "Görseller"))
print(cut("Görseller", "Müzik"))
EOF
  video=$(find "$dir" -name short.mp4 | head -1)
  if [ -n "$FF" ] && [ -n "$video" ]; then
    for t in 2 9 16 23; do "$FF" -v error -y -ss "$t" -i "$video" -frames:v 1 -vf scale=270:-1 "$dir/k$t.jpg"; done
    "$FF" -v error -y -i "$dir/k2.jpg" -i "$dir/k9.jpg" -i "$dir/k16.jpg" -i "$dir/k23.jpg" \
      -filter_complex hstack=4 "$dir/kareler.jpg" && echo "Kareler: $dir/kareler.jpg"
  else
    echo "ffmpeg yok: kareler çıkarılamadı (pip install imageio-ffmpeg)"
  fi
done
