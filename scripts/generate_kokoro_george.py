#!/usr/bin/env python3
"""Narrate scripts with Kokoro's British male George (bm_george)."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

RATE = 24000
VOICE = "bm_george"

def split_text(text, limit=650):
    """Preserve sentence endings and paragraph pauses while bounding memory."""
    out = []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for paragraph in paragraphs:
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        group = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(group) + len(sentence) + 1 > limit and group:
                out.append((group, False))
                group = ""
            if len(sentence) > limit:
                words = sentence.split()
                for word in words:
                    if len(group) + len(word) + 1 > limit and group:
                        out.append((group, False))
                        group = ""
                    group = (group + " " + word).strip()
            else:
                group = (group + " " + sentence).strip()
        if group:
            out.append((group, True))
    return out

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--speed", type=float, default=0.90)
    p.add_argument("--preview", action="store_true")
    p.add_argument("--chunk-chars", type=int, default=650)
    args = p.parse_args()

    if not 0.75 <= args.speed <= 1.15:
        p.error("speed must be between 0.75 and 1.15")
    if not 200 <= args.chunk_chars <= 1000:
        p.error("chunk-chars must be between 200 and 1000")
    source = Path(args.script)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        p.error("Input text file is empty")
    if args.preview and len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0].strip()
    sections = split_text(text, args.chunk_chars)
    if not sections:
        p.error("No speakable text found")

    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    pipeline = KPipeline(lang_code="b", device="cpu")
    elapsed = 0.0

    with tempfile.TemporaryDirectory(prefix="kokoro-george-") as scratch:
        scratch = Path(scratch)
        concat = []
        for index, (chunk, paragraph_end) in enumerate(sections, start=1):
            print(f"Kokoro George: section {index}/{len(sections)} ({len(chunk)} chars)", flush=True)
            pieces = []
            for _, _, audio in pipeline(chunk, voice=VOICE, speed=args.speed):
                piece = np.asarray(audio, dtype=np.float32).reshape(-1)
                if piece.size:
                    pieces.append(piece)
            if not pieces:
                raise RuntimeError(f"No speech generated for section {index}")
            # Avoid synthetic truncation: give the narrator a natural pause
            # at the end of each section and a longer pause between paragraphs.
            pause = np.zeros(int(RATE * (0.60 if paragraph_end else 0.30)), dtype=np.float32)
            wave = np.concatenate([*pieces, pause])
            elapsed += len(wave) / RATE
            wav_file = scratch / f"part_{index:04d}.wav"
            sf.write(wav_file, wave, RATE, subtype="PCM_16")
            concat.append(wav_file)

        listing = scratch / "files.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in concat), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame",
            "-b:a", "96k", str(target / "narration.mp3")
        ], check=True)

    size = (target / "narration.mp3").stat().st_size
    if size < 1000 or size > 95_000_000:
        raise RuntimeError(f"Output MP3 size invalid for GitHub: {size} bytes")
    (target / "script.txt").write_text(text + "\n", encoding="utf-8")
    meta = {"engine":"kokoro-82m","voice":VOICE,"accent":"British English",
            "speed":args.speed,"preview":args.preview,"sections":len(sections),
            "duration_seconds":round(elapsed,2),"audio":"narration.mp3"}
    (target / "manifest.json").write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    print(f"Ready: {target / 'narration.mp3'} ({size:,} bytes, {elapsed:.1f}s)",flush=True)

if __name__ == "__main__":
    main()
