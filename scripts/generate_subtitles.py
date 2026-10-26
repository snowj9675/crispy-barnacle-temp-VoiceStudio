#!/usr/bin/env python3
"""Transcribe the FINAL narration MP3 with word timings and produce SRT/ASS/JSON."""
import argparse
import json
import re
from pathlib import Path

def ass_escape(s):
    return s.replace("\\", r"\\").replace("{", "(").replace("}", ")")

def srt_stamp(t):
    ms = max(0, round(t * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def ass_stamp(t):
    cs = max(0, round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def group_words(words, max_words=7, max_chars=47, max_seconds=3.5):
    groups, group = [], []
    for word in words:
        if group and (
            len(group) >= max_words or
            sum(len(x["word"]) + 1 for x in group) + len(word["word"]) > max_chars or
            word["end"] - group[0]["start"] > max_seconds or
            word["start"] - group[-1]["end"] > 0.9
        ):
            groups.append(group)
            group = []
        group.append(word)
        if re.search(r"[.!?]$", word["word"]) and len(group) >= 3:
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    return groups

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--model", default="small.en")
    p.add_argument("--font", default="DejaVu Sans")
    args = p.parse_args()
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    print(f"Loading faster-whisper {args.model} (cached when available)",flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        args.audio, language="en", word_timestamps=True,
        vad_filter=False, beam_size=5, condition_on_previous_text=False
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            token = w.word.strip()
            if not token:
                continue
            a, b = max(0.,float(w.start)),max(0.,float(w.end))
            if b <= a:
                b = a + 0.08
            words.append({"word":token,"start":round(a,3),"end":round(b,3)})
    if not words:
        raise RuntimeError("Speech alignment returned zero words")
    groups = group_words(words)

    # Karaoke highlights spoken word, other words stay readable.
    # ASS \k counts centiseconds, and starts in SecondaryColour, switching to PrimaryColour.
    # Primary warm ivory, secondary muted grey. Black semi-transparent box.
    header = """[Script Info]
Title: Human Thesis — Word Sync Captions
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Narration,%s,55,&H0000E8FF,&H00FFFFFF,&H55000000,&H8A101010,-1,0,0,0,100,100,0,0,3,16,0,5,160,160,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" % args.font
    # Note: ASS colors are BBGGRR. Primary &H0000E8FF is warm gold; secondary white.
    ass_lines = [header]
    srt_lines = []
    cues = []
    for idx, group in enumerate(groups, 1):
        start, end = group[0]["start"], group[-1]["end"]
        end = max(end, start + 0.1)
        # centered just below midpoint. Explicit pos works independently of MarginV.
        tokens = []
        cursor = start
        for w in group:
            pause_cs = max(0, round((w["start"] - cursor)*100))
            if pause_cs:
                tokens.append(r"{\k%d}" % pause_cs)
            duration_cs = max(8,round((w["end"]-w["start"])*100))
            tokens.append(r"{\k%d}%s " % (duration_cs, ass_escape(w["word"])))
            cursor = w["end"]
        payload = r"{\an5\pos(960,735)}" + "".join(tokens).rstrip()
        ass_lines.append(
            f"Dialogue: 0,{ass_stamp(start)},{ass_stamp(end)},Narration,,0,0,0,,{payload}\n"
        )
        phrase = " ".join(w["word"] for w in group)
        srt_lines.append(f"{idx}\n{srt_stamp(start)} --> {srt_stamp(end)}\n{phrase}\n\n")
        cues.append({"start":start,"end":end,"text":phrase,"words":group})
    (target/"captions.ass").write_text("".join(ass_lines),encoding="utf-8")
    (target/"captions.srt").write_text("".join(srt_lines),encoding="utf-8")
    (target/"word_timings.json").write_text(
        json.dumps({"language":"en","model":args.model,
                    "timing_source":"ASR on final MP3; review proper names",
                    "resolution":[1920,1080],"cues":cues},indent=2,ensure_ascii=False)+"\n",
        encoding="utf-8"
    )
    print(f"Captioned {len(words)} words into {len(cues)} cues",flush=True)

if __name__=="__main__":
    main()
