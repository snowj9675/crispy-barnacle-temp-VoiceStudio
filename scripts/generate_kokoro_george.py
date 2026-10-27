#!/usr/bin/env python3
"""Long-form Kokoro George narration with deliberate pauses and subtle mastering."""
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

def split_long_sentence(sentence, limit):
    """Prefer clause boundaries; never let a single TTS request become enormous."""
    if len(sentence) <= limit:
        return [sentence]
    clauses = re.split(r"(?<=[,;:])\s+", sentence)
    parts, current = [], ""
    for clause in clauses:
        if len(clause) > limit:
            if current:
                parts.append(current)
                current = ""
            words = clause.split()
            for word in words:
                if len(current) + len(word) + 1 > limit and current:
                    parts.append(current)
                    current = ""
                current = (current + " " + word).strip()
        elif len(current) + len(clause) + 1 > limit and current:
            parts.append(current)
            current = clause
        else:
            current = (current + " " + clause).strip()
    if current:
        parts.append(current)
    return parts

def split_text(text, limit=650, sentence_pause_ms=340,
               paragraph_pause_ms=880, question_pause_ms=500):
    """Return independently spoken sentence/clauses and silence after each.

    Segmentation prevents long paragraphs from being rushed in a single
    synth call. Only paragraph endings receive paragraph-length breaks.
    """
    sections = []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for paragraph in paragraphs:
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        # Keep abbreviations from causing artificial sentence breaks.
        protected = re.sub(r"\b(Mr|Mrs|Ms|Dr|Prof|St|vs)\.", r"\1<DOT>", paragraph)
        sentences = re.split(r"(?<=[.!?])\s+", protected)
        sentences = [s.replace("<DOT>", ".").strip() for s in sentences if s.strip()]
        expanded = []
        for sentence in sentences:
            expanded.extend(split_long_sentence(sentence, limit))
        for index, sentence in enumerate(expanded):
            last_in_para = index == len(expanded) - 1
            punctuation = sentence.rstrip("”’\"' )")
            if last_in_para:
                pause = paragraph_pause_ms
                kind = "paragraph"
            elif punctuation.endswith("?"):
                pause = question_pause_ms
                kind = "question"
            elif punctuation.endswith((";", ":")):
                pause = max(sentence_pause_ms, question_pause_ms)
                kind = "reflection"
            else:
                pause = sentence_pause_ms
                kind = "sentence"
            sections.append({"text":sentence,"pause_ms":pause,"kind":kind})
    return sections

def build_master_filter(style):
    if style == "none":
        return None
    # Gentle voice leveling with light rumble removal, not a radio-style crush.
    return ("highpass=f=65,"
            "acompressor=threshold=0.16:ratio=1.5:attack=16:release=230:makeup=1.0,"
            "loudnorm=I=-17:TP=-1.5:LRA=11")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--speed", type=float, default=0.90)
    p.add_argument("--preview", action="store_true")
    p.add_argument("--chunk-chars", type=int, default=650)
    p.add_argument("--sentence-pause-ms", type=int, default=340)
    p.add_argument("--paragraph-pause-ms", type=int, default=880)
    p.add_argument("--question-pause-ms", type=int, default=500)
    p.add_argument("--mastering", choices=["gentle","none"], default="gentle")
    args = p.parse_args()

    if not 0.75 <= args.speed <= 1.15:
        p.error("speed must be 0.75..1.15")
    if not 200 <= args.chunk_chars <= 1000:
        p.error("chunk-chars must be 200..1000")
    for name in ("sentence_pause_ms","paragraph_pause_ms","question_pause_ms"):
        if not 0 <= getattr(args,name) <= 2500:
            p.error(f"{name} must be 0..2500")
    if args.paragraph_pause_ms < args.sentence_pause_ms:
        p.error("paragraph pause must be at least sentence pause")
    source = Path(args.script)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        p.error("Input script is empty")
    if args.preview and len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0].strip()

    sections = split_text(text, args.chunk_chars, args.sentence_pause_ms,
                          args.paragraph_pause_ms, args.question_pause_ms)
    if not sections:
        p.error("No spoken sections found")
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    pipeline = KPipeline(lang_code="b", device="cpu")
    sample_count = 0
    pause_count = 0
    levels = []

    with tempfile.TemporaryDirectory(prefix="kokoro-george-") as tmp:
        scratch = Path(tmp)
        concat = []
        for index, part in enumerate(sections, start=1):
            chunk = part["text"]
            print(f"George {index}/{len(sections)} [{part['kind']}]: {len(chunk)} chars",
                  flush=True)
            pieces = []
            for _, _, audio in pipeline(chunk, voice=VOICE, speed=args.speed):
                segment = np.asarray(audio, dtype=np.float32).reshape(-1)
                if segment.size:
                    pieces.append(segment)
            if not pieces:
                raise RuntimeError(f"Empty Kokoro audio for section {index}")
            pause_samples = int(RATE * part["pause_ms"] / 1000)
            # No crossfade into silence: preserve natural consonant tails.
            wave = np.concatenate([
                *pieces, np.zeros(pause_samples, dtype=np.float32)
            ])
            wav_file = scratch / f"part_{index:04d}.wav"
            sf.write(wav_file, wave, RATE, subtype="PCM_16")
            concat.append(wav_file)
            sample_count += len(wave)
            pause_count += pause_samples
            levels.append(float(np.max(np.abs(wave))))

        listing = scratch / "files.txt"
        listing.write_text("".join(f"file '{x}'\n" for x in concat),encoding="utf-8")
        command = ["ffmpeg","-hide_banner","-loglevel","error","-y",
                   "-f","concat","-safe","0","-i",str(listing)]
        af = build_master_filter(args.mastering)
        if af:
            command += ["-af",af]
        command += ["-ac","1","-ar","24000","-codec:a","libmp3lame",
                    "-b:a","128k",str(target/"narration.mp3")]
        subprocess.run(command,check=True)

    duration = sample_count / RATE
    size = (target/"narration.mp3").stat().st_size
    if size < 1000 or size > 95_000_000:
        raise RuntimeError(f"Invalid output MP3 size for GitHub: {size}")
    (target/"script.txt").write_text(text + "\n",encoding="utf-8")
    meta = {
        "engine":"kokoro-82m","voice":VOICE,
        "accent":"British English","speed":args.speed,
        "preview":args.preview,"sections":len(sections),
        "duration_seconds":round(duration,2),
        "pacing_profile":"human-thesis-reflective-v2",
        "sentence_pause_ms":args.sentence_pause_ms,
        "paragraph_pause_ms":args.paragraph_pause_ms,
        "question_pause_ms":args.question_pause_ms,
        "pause_seconds":round(pause_count/RATE,2),
        "mastering":args.mastering,
        "loudness_target_lufs":(-17 if af else None),
        "peak_before_mastering":round(max(levels),4),
        "bitrate_kbps":128,"audio":"narration.mp3",
    }
    (target/"manifest.json").write_text(
        json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    print(f"Ready: {target/'narration.mp3'} ({size:,} bytes, "
          f"{duration:.1f}s, intentional pauses {pause_count/RATE:.1f}s)",
          flush=True)

if __name__ == "__main__":
    main()
