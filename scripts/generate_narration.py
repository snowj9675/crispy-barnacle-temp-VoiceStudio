#!/usr/bin/env python3
"""Generate long-form speech, one bounded chunk at a time, through VoiceStudio."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import wave

def chunks(text, limit):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units = []
    for paragraph in paragraphs:
        # Split on sentence boundaries; preserve punctuation.
        units.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph) if s.strip())
    out, current = [], ""
    for unit in units:
        # Preserve every character, even when an unusually long sentence must be split.
        words = unit.split()
        for word in words:
            candidate = (current + " " + word).strip()
            if len(candidate) > limit and current:
                out.append(current)
                current = word
            else:
                current = candidate
    if current:
        out.append(current)
    return out

def run(cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)

def synthesize(text, path, args):
    cmd = [
        "curl", "--fail-with-body", "--silent", "--show-error", "--max-time", "1800",
        "--output", str(path),
        "--header", "Authorization: Bearer " + os.environ["OMNIVOICE_API_KEY"],
        "--form-string", "text=" + text,
        "--form-string", "language=" + args.language,
        "--form-string", "instruct=" + args.voice_instruct,
        "--form-string", "speed=" + str(args.speed),
        "--form-string", "effect_preset=broadcast",
        "--form-string", "max_chunk_chars=0",
        "http://127.0.0.1:3900/generate",
    ]
    try:
        run(cmd)
        with wave.open(str(path), "rb") as f:
            if f.getnframes() < 1000:
                raise ValueError("Generated WAV is unusually short")
            return f.getnframes() / f.getframerate()
    except Exception:
        if path.exists():
            print("TTS endpoint failed (first 1200 bytes):", path.read_bytes()[:1200], file=sys.stderr)
        raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--voice-instruct", default="male, middle-aged, low pitch, american accent")
    parser.add_argument("--speed", type=float, default=0.88)
    parser.add_argument("--chunk-chars", type=int, default=400)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if not (0.7 <= args.speed <= 1.2):
        parser.error("speed must be between 0.7 and 1.2")
    if not (150 <= args.chunk_chars <= 750):
        parser.error("chunk-chars must be 150..750")
    source = Path(args.script)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        parser.error("script is empty")
    if args.preview:
        text = text[:500].rsplit(" ", 1)[0].strip()
    parts = chunks(text, args.chunk_chars)
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    wav_files, lengths = [], []
    with tempfile.TemporaryDirectory(prefix="voicestudio-") as tmp:
        for idx, part in enumerate(parts, 1):
            print(f"Rendering chunk {idx}/{len(parts)} ({len(part)} chars)", flush=True)
            wav = Path(tmp) / f"chunk-{idx:04}.wav"
            lengths.append(synthesize(part, wav, args))
            wav_files.append(wav)
        concat_file = Path(tmp) / "concat.txt"
        # Decode-and-concatenate safely, using FFmpeg concat demuxer.
        concat_file.write_text("".join("file '" + str(p) + "'\n" for p in wav_files))
        # A consistent, speech-oriented MP3 avoids GitHub's 100 MB per-file limit.
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-ac", "1", "-ar", "24000", "-b:a", "64k", str(target / "narration.mp3")])
    (target / "script.txt").write_text(text + "\n", encoding="utf-8")
    manifest = {
        "profile": "calm-reflective-narrator",
        "language": args.language,
        "voice_instruct": args.voice_instruct,
        "speed": args.speed,
        "preview": args.preview,
        "chunks": len(parts),
        "estimated_audio_seconds": round(sum(lengths), 2),
        "audio": "narration.mp3",
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    size = (target / "narration.mp3").stat().st_size
    if size >= 95_000_000:
        raise RuntimeError("MP3 would be too large to push into GitHub (95MB safety threshold)")
    print(f"Generated {size:,} bytes; {sum(lengths):.1f}s of narration", flush=True)

if __name__ == "__main__":
    main()
