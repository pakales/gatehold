#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$ROOT/media/shot-manifest.json"
CARDS="$ROOT/media/cards"
RAW="$ROOT/media/audio/raw"
FINAL_AUDIO="$ROOT/media/audio/final"
SEGMENTS="$ROOT/media/output/segments"
OUTPUT="$ROOT/media/output/gatehold-build-week-demo-1080p.mp4"
SRT="$ROOT/media/output/gatehold-build-week-demo.en.srt"
CONCAT="$ROOT/media/output/segments.txt"

mkdir -p "$CARDS" "$FINAL_AUDIO" "$SEGMENTS" "$(dirname "$OUTPUT")"

node "$ROOT/scripts/video/render-cards.mjs"
for svg in "$CARDS"/*.svg; do
  png="${svg%.svg}.png"
  if [[ ! -s "$png" ]]; then
    magick -font /System/Library/Fonts/Helvetica.ttc \
      -background none -density 144 "$svg" -resize 1920x1080! "$png"
  fi
done

rm -f "$CONCAT" "$SRT"
sequence=0
cursor_ms=0

format_srt_time() {
  local total_ms="$1"
  local hours minutes seconds millis
  hours=$((total_ms / 3600000))
  minutes=$(((total_ms % 3600000) / 60000))
  seconds=$(((total_ms % 60000) / 1000))
  millis=$((total_ms % 1000))
  printf '%02d:%02d:%02d,%03d' "$hours" "$minutes" "$seconds" "$millis"
}

while IFS=$'\t' read -r id duration visual motion narration; do
  sequence=$((sequence + 1))
  input="$ROOT/$visual"
  raw="$RAW/$id.wav"
  normalized="$FINAL_AUDIO/$id.wav"
  segment="$SEGMENTS/$id.mp4"

  [[ -s "$input" ]] || { printf 'Missing visual: %s\n' "$input" >&2; exit 1; }
  [[ -s "$raw" ]] || { printf 'Missing narration: %s\n' "$raw" >&2; exit 1; }

  raw_duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$raw")"
  awk -v raw="$raw_duration" -v slot="$duration" 'BEGIN { exit !(raw <= slot - 0.20) }' || {
    printf '%s narration %.3fs does not fit %.3fs slot.\n' "$id" "$raw_duration" "$duration" >&2
    exit 1
  }

  ffmpeg -nostdin -y -hide_banner -loglevel error \
    -i "$raw" \
    -af "loudnorm=I=-16:LRA=7:TP=-1.5,apad=pad_dur=$duration,atrim=duration=$duration,aresample=48000" \
    -ar 48000 -ac 2 "$normalized"

  case "$motion" in
    push-in)
      zoom_expr="min(zoom+0.00018,1.035)"
      x_expr="iw/2-(iw/zoom/2)"
      ;;
    drift-left)
      zoom_expr="1.025"
      x_expr="min((on/((30*$duration)-1))*40,40)"
      ;;
    drift-right)
      zoom_expr="1.025"
      x_expr="max(40-(on/((30*$duration)-1))*40,0)"
      ;;
    *)
      zoom_expr="1.0"
      x_expr="0"
      ;;
  esac

  ffmpeg -nostdin -y -hide_banner -loglevel error \
    -loop 1 -framerate 30 -t "$duration" -i "$input" \
    -i "$normalized" \
    -vf "scale=1980:1114:force_original_aspect_ratio=increase:flags=lanczos,crop=1980:1114,zoompan=z='$zoom_expr':x='$x_expr':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,format=yuv420p,fade=t=in:st=0:d=0.35,fade=t=out:st=$(awk -v d="$duration" 'BEGIN{printf "%.3f",d-0.35}'):d=0.35" \
    -map 0:v:0 -map 1:a:0 \
    -c:v libx264 -preset medium -crf 17 -r 30 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 -ac 2 \
    -t "$duration" -movflags +faststart "$segment"

  printf "file '%s'\n" "$segment" >> "$CONCAT"

  start_ms="$cursor_ms"
  end_ms=$((cursor_ms + duration * 1000))
  {
    printf '%d\n' "$sequence"
    printf '%s --> %s\n' "$(format_srt_time "$start_ms")" "$(format_srt_time "$end_ms")"
    printf '%s\n\n' "$narration"
  } >> "$SRT"
  cursor_ms="$end_ms"
done < <(
  jq -r '.shots[] | [.id, (.durationSeconds|tostring), .visual, .motion, .narration] | @tsv' "$MANIFEST"
)

ffmpeg -nostdin -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$CONCAT" \
  -c copy -movflags +faststart "$OUTPUT"

printf 'Built %s\n' "$OUTPUT"
printf 'Captions %s\n' "$SRT"
