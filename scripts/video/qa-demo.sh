#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$ROOT/media/shot-manifest.json"
FINAL="${1:-$ROOT/media/output/gatehold-build-week-demo-1080p.mp4}"
SRT="$ROOT/media/output/gatehold-build-week-demo.en.srt"
REVIEW="$ROOT/media/review"
PROBE="$REVIEW/ffprobe.json"
LOUDNESS="$REVIEW/loudness.json"
CONTACT="$REVIEW/contact-sheet.png"
REPORT="$REVIEW/qa-report.json"
CHECKSUMS="$REVIEW/checksums.sha256"

mkdir -p "$REVIEW"
[[ -s "$FINAL" ]] || { printf 'Missing final video: %s\n' "$FINAL" >&2; exit 1; }
[[ -s "$SRT" ]] || { printf 'Missing captions: %s\n' "$SRT" >&2; exit 1; }

ffprobe -v error -show_format -show_streams -of json "$FINAL" > "$PROBE"

duration="$(jq -r '.format.duration | tonumber' "$PROBE")"
expected="$(jq -r '.targetDurationSeconds' "$MANIFEST")"
width="$(jq -r '.streams[] | select(.codec_type == "video") | .width' "$PROBE")"
height="$(jq -r '.streams[] | select(.codec_type == "video") | .height' "$PROBE")"
video_codec="$(jq -r '.streams[] | select(.codec_type == "video") | .codec_name' "$PROBE")"
pixel_format="$(jq -r '.streams[] | select(.codec_type == "video") | .pix_fmt' "$PROBE")"
frame_rate="$(jq -r '.streams[] | select(.codec_type == "video") | .r_frame_rate' "$PROBE")"
audio_codec="$(jq -r '.streams[] | select(.codec_type == "audio") | .codec_name' "$PROBE")"
sample_rate="$(jq -r '.streams[] | select(.codec_type == "audio") | .sample_rate' "$PROBE")"
channels="$(jq -r '.streams[] | select(.codec_type == "audio") | .channels' "$PROBE")"

awk -v actual="$duration" -v expected="$expected" \
  'BEGIN { exit !(actual >= expected - 0.20 && actual <= expected + 0.20 && actual < 180) }' || {
  printf 'Duration gate failed: actual=%ss expected=%ss\n' "$duration" "$expected" >&2
  exit 1
}
[[ "$width" == "1920" && "$height" == "1080" ]] || { printf 'Resolution gate failed.\n' >&2; exit 1; }
[[ "$video_codec" == "h264" && "$pixel_format" == "yuv420p" && "$frame_rate" == "30/1" ]] || {
  printf 'Video format gate failed.\n' >&2
  exit 1
}
[[ "$audio_codec" == "aac" && "$sample_rate" == "48000" && "$channels" == "2" ]] || {
  printf 'Audio format gate failed.\n' >&2
  exit 1
}

ffmpeg -nostdin -hide_banner -nostats -i "$FINAL" \
  -map 0:a:0 -af loudnorm=I=-16:LRA=7:TP=-1.5:print_format=json \
  -f null - 2> "$REVIEW/loudness.log"
sed -n '/^{/,/^}/p' "$REVIEW/loudness.log" > "$LOUDNESS"
integrated="$(jq -r '.input_i | tonumber' "$LOUDNESS")"
true_peak="$(jq -r '.input_tp | tonumber' "$LOUDNESS")"
awk -v value="$integrated" 'BEGIN { exit !(value >= -17.0 && value <= -15.0) }' || {
  printf 'Loudness gate failed: %s LUFS\n' "$integrated" >&2
  exit 1
}
awk -v value="$true_peak" 'BEGIN { exit !(value <= -1.0) }' || {
  printf 'True peak gate failed: %s dBTP\n' "$true_peak" >&2
  exit 1
}

ffmpeg -nostdin -hide_banner -v error -i "$FINAL" -f null -
ffmpeg -nostdin -y -hide_banner -loglevel error \
  -i "$FINAL" \
  -vf "fps=1/12,scale=480:270:force_original_aspect_ratio=decrease:flags=lanczos,pad=480:270:(ow-iw)/2:(oh-ih)/2,tile=4x4" \
  -frames:v 1 "$CONTACT"

node - "$MANIFEST" "$SRT" <<'NODE'
const fs = require("node:fs");
const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const srt = fs.readFileSync(process.argv[3], "utf8");
const actual = srt
  .replace(/^\d+$/gm, "")
  .replace(/^\d\d:\d\d:\d\d,\d{3} --> .*$/gm, "")
  .replace(/\s+/g, " ")
  .trim();
const expected = manifest.shots.map((shot) => shot.narration).join(" ").replace(/\s+/g, " ").trim();
if (actual !== expected) {
  throw new Error("Caption text does not exactly match the approved narration.");
}
process.stdout.write(`Captions exact: ${manifest.shots.length} shots\n`);
NODE

(
  cd "$ROOT"
  shasum -a 256 \
    "media/output/$(basename "$FINAL")" \
    "media/output/$(basename "$SRT")" \
    "media/shot-manifest.json"
) > "$CHECKSUMS"

jq -n \
  --arg status "PASS" \
  --argjson durationSeconds "$duration" \
  --arg resolution "${width}x${height}" \
  --arg video "${video_codec}/${pixel_format}/${frame_rate}" \
  --arg audio "${audio_codec}/${sample_rate}Hz/${channels}ch" \
  --argjson integratedLufs "$integrated" \
  --argjson truePeakDbtp "$true_peak" \
  --arg contactSheet "media/review/contact-sheet.png" \
  --arg disclosure "$(jq -r '.voice.disclosure' "$MANIFEST")" \
  '{
    status: $status,
    durationSeconds: $durationSeconds,
    resolution: $resolution,
    video: $video,
    audio: $audio,
    integratedLufs: $integratedLufs,
    truePeakDbtp: $truePeakDbtp,
    decodeErrors: 0,
    captionsExact: true,
    aiVoiceDisclosure: $disclosure,
    contactSheet: $contactSheet,
    manualVisualReviewRequired: true
  }' > "$REPORT"

printf 'PASS duration=%ss video=%s audio=%s loudness=%sLUFS peak=%sdBTP\n' \
  "$duration" "${video_codec}/${pixel_format}/${frame_rate}" \
  "${audio_codec}/${sample_rate}Hz/${channels}ch" "$integrated" "$true_peak"
printf 'Manual visual review: %s\n' "$CONTACT"
printf 'Report: %s\n' "$REPORT"
