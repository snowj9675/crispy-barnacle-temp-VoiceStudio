#!/usr/bin/env python3
"""Human Thesis video builder: editorial input, footage selection, FFmpeg render, R2 publish."""
import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, quote

import requests
import yaml

RATE = 24
REJECT = re.compile(
    r"\b(?:bikini|swimwear|swimsuit|beach|beachwear|sunbathing|poolside|"
    r"lingerie|underwear|nude|nudity|topless|sexy|sensual|glamour|glamorous|"
    r"tropical\s+resort|summer\s+vacation|fashion\s+model|fashion\s+shoot|"
    r"party\s+girls|nightclub|surfing|luxury\s+hotel|wedding\s+dress)\b", re.I)
HOSTS = ("pexels.com", "pixabay.com", "vimeocdn.com")
TOPICS = {
    "shadow": ["shadow", "darkness", "silhouette", "fog", "mirror", "reflection", "identity", "mask"],
    "society": ["society", "crowd", "city", "street", "urban", "conformity", "people walking"],
    "solitude": ["alone", "lonely", "solitude", "isolation", "single person", "empty room", "window"],
    "self": ["self awareness", "mind", "introspection", "thinking", "contemplation", "reflection"],
    "stoic": ["statue", "roman", "greek", "ancient", "marble", "philosopher", "library"],
    "power": ["chess", "strategy", "king", "power", "palace", "leadership", "authority"],
    "freedom": ["mountain", "open road", "horizon", "freedom", "sunrise", "walking away"],
    "fear": ["storm", "dark", "anxiety", "tunnel", "rain", "fog", "night"],
    "healing": ["sunlight", "nature", "forest", "light", "hope", "transformation"],
    "time": ["clock", "hourglass", "time", "old book", "age", "history"],
    "boundaries": ["door", "gate", "distance", "walking away", "separation", "alone"],
    "betrayal": ["two people", "separation", "argument", "loneliness", "empty chair"],
    "knowledge": ["library", "book", "writing", "manuscript", "study", "philosophy"],
}
ALIASES = {
    "jung":"shadow", "shadow":"shadow", "unconscious":"shadow", "persona":"shadow",
    "mask":"shadow", "projection":"shadow", "identity":"shadow",
    "society":"society", "social":"society", "crowd":"society", "conformity":"society",
    "lonely":"solitude", "alone":"solitude", "silence":"solitude", "quiet":"solitude",
    "self":"self", "awareness":"self", "understand":"self", "thought":"self",
    "stoic":"stoic", "marcus":"stoic", "seneca":"stoic", "aurelius":"stoic",
    "power":"power", "control":"power", "machiavelli":"power", "manipulation":"power",
    "freedom":"freedom", "independent":"freedom", "sovereignty":"freedom",
    "fear":"fear", "anxiety":"fear", "trauma":"fear",
    "healing":"healing", "growth":"healing", "change":"healing",
    "time":"time", "mortality":"time", "death":"time",
    "boundaries":"boundaries", "reject":"boundaries", "approval":"boundaries",
    "betray":"betrayal", "relationship":"betrayal", "resentment":"betrayal",
    "wisdom":"knowledge", "learn":"knowledge", "philosophy":"knowledge",
}
def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)

def command(args, **kw):
    subprocess.run(args, check=True, **kw)

def ffprobe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=width,height,codec_type",
        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    info = json.loads(p.stdout)
    dur = float(info.get("format", {}).get("duration") or 0)
    video = next((x for x in info.get("streams", []) if x.get("codec_type") == "video"), {})
    return dur, int(video.get("width") or 0), int(video.get("height") or 0)

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:70] or "episode"

def parse_episode(path, output, override):
    root = (Path.cwd() / "input").resolve()
    path = Path(path).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".md":
        raise ValueError("Episode must be a .md file inside input/")
    data = path.read_text(encoding="utf-8")
    if not data.startswith("---\n") or "\n---\n" not in data[4:]:
        raise ValueError("Episode requires YAML front matter between --- lines")
    head, body = data[4:].split("\n---\n", 1)
    meta = yaml.safe_load(head)
    if not isinstance(meta, dict):
        raise ValueError("Episode metadata must be YAML mapping")
    body = body.strip()
    if not body or len(body) < 50:
        raise ValueError("Narration content too short")
    name = slugify(meta.get("slug") or meta.get("title") or path.stem)
    meta["slug"] = name
    meta["source_file"] = str(path.relative_to(Path.cwd()))
    meta["preview"] = str(override).lower() == "true" if override else bool(meta.get("preview", True))
    speed = float((meta.get("voice") or {}).get("speed", 0.90))
    if not 0.75 <= speed <= 1.15:
        raise ValueError("Kokoro speed outside 0.75..1.15")
    meta["voice"] = {"engine":"kokoro", "preset":"bm_george", "speed":speed}
    Path(output).mkdir(parents=True, exist_ok=True)
    (Path(output) / "narration_source.txt").write_text(body + "\n", encoding="utf-8")
    write_json(Path(output) / "episode.json", meta)
    print(f"Prepared '{name}', preview={meta['preview']}, speed={speed}", flush=True)

def allowed_direct_video(url):
    if not isinstance(url, str):
        return False
    p = urlparse(url)
    return p.scheme == "https" and any(p.hostname == h or
           (p.hostname or "").endswith("." + h) for h in HOSTS)

def norm(v):
    if not isinstance(v, dict):
        return None
    if v.get("approved") is False or str(v.get("status","")).lower() in ("rejected","pending","review","blocked"):
        return None
    url = v.get("video_url") or v.get("download_url") or v.get("file_url")
    if not url and isinstance(v.get("video_files"), list):
        variants = [x for x in v["video_files"] if isinstance(x,dict) and x.get("link")]
        variants.sort(key=lambda x: abs(int(x.get("height") or 720)-1080))
        url = variants[0]["link"] if variants else ""
    if not allowed_direct_video(url):
        return None
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if w and h and w/h < 1.38:
        return None
    if w and w < 640 or h and h < 360:
        return None
    cats = v.get("categories") or v.get("category") or []
    cats = cats if isinstance(cats, list) else [cats]
    queries = v.get("queries") or v.get("query") or v.get("search_terms") or []
    queries = queries if isinstance(queries, list) else [queries]
    tags = v.get("tags") or v.get("themes") or []
    tags = tags if isinstance(tags, list) else [tags]
    # Exclude obvious off-brand footage; metadata alone is not visual verification.
    fields = [v.get("title",""),v.get("description",""),*cats,*queries,*tags]
    semantic = " ".join(str(x) for x in fields).lower()
    if REJECT.search(semantic):
        return None
    uid = str(v.get("uid") or v.get("source","") + ":" + str(v.get("id","")) or url)
    return {"uid":uid,"url":url,"page_url":v.get("page_url") or v.get("source_page") or "",
        "source":v.get("source") or v.get("provider") or "",
        "title":v.get("title") or "", "categories":cats, "queries":queries,
        "tags":tags,"semantic":semantic, "width":w,"height":h,
        "duration":float(v.get("duration") or v.get("duration_seconds") or 0)}

def scene_topics(text):
    low = text.lower()
    found = {topic for alias,topic in ALIASES.items() if re.search(r"\b"+re.escape(alias)+r"\b",low)}
    return found or {"self","knowledge"}

def get_catalog(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw if isinstance(raw,list) else raw.get("videos", [])
    if not rows:
        raise RuntimeError("catalog.json has no videos list")
    out, seen = [], set()
    for row in rows:
        x = norm(row)
        if x and x["uid"] not in seen:
            seen.add(x["uid"])
            out.append(x)
    if not out:
        raise RuntimeError("No eligible video URLs after safety checks")
    print(f"Catalog: {len(rows)} entries, {len(out)} safe-format landscape candidates",flush=True)
    return out

def pick(catalog, topics, text, prior, seed, hints, exclusions):
    extra = " ".join(hints)
    tokens = set(re.findall(r"[a-z]{4,}", text.lower()))
    forbidden = re.compile("|".join(r"\b"+re.escape(t.lower())+r"\b" for t in exclusions) if exclusions else r"(?!)",re.I)
    scored = []
    for item in catalog:
        s = item["semantic"]
        if forbidden.search(s):
            continue
        score = 0.
        for topic in topics:
            if topic in s:
                score += 8
            score += sum(2 for term in TOPICS.get(topic,[]) if term in s)
        score += sum(1 for tok in tokens if tok in s)
        score += sum(2 for t in hints if str(t).lower() in s)
        if item["uid"] in prior[-5:]:
            score -= 35
        if item["width"] and item["height"] and item["width"]/item["height"] >= 1.7:
            score += 2
        if item["duration"] >= 10:
            score += 2
        # stable tie break; avoids selecting the same top clip in every scene
        tie = int(hashlib.sha256((str(seed)+item["uid"]).encode()).hexdigest()[:8],16)/2**32
        scored.append((score + tie,item))
    if not scored:
        raise RuntimeError("No clips match episode exclusions")
    scored.sort(reverse=True,key=lambda x:x[0])
    return scored[0][1], round(scored[0][0],2)

def plan(output, catalog_file):
    output = Path(output)
    meta = json.loads((output/"episode.json").read_text())
    cues = json.loads((output/"word_timings.json").read_text())["cues"]
    duration,_,_ = ffprobe(output/"narration.mp3")
    catalog = get_catalog(catalog_file)
    # Full films reuse an editorial pool instead of downloading a new file for
    # every 14-second scene. Keeps runner storage and bandwidth bounded.
    max_unique = max(4, int(os.environ.get("MAX_UNIQUE_CLIPS", "42")))
    chosen = {}
    visuals = meta.get("visuals") or {}
    hints = visuals.get("keywords") or visuals.get("search_tags") or []
    exclusions = visuals.get("avoid") or []
    if isinstance(hints,str): hints=[hints]
    if isinstance(exclusions,str): exclusions=[exclusions]
    sections = []
    prior = []
    t = 0.
    scene_sec = float(visuals.get("scene_seconds",12))
    if not 6 <= scene_sec <= 22:
        raise ValueError("scene_seconds must be 6..22")
    i=0
    while t < duration-0.05:
        span = min(scene_sec,duration-t)
        scene_text = " ".join(c["text"] for c in cues
            if float(c["end"]) > t and float(c["start"]) < t+span)
        topics = sorted(scene_topics(scene_text))
        pool = catalog if len(chosen) < max_unique else list(chosen.values())
        item,score = pick(pool,topics,scene_text,prior, i, hints, exclusions)
        chosen[item["uid"]] = item
        prior.append(item["uid"])
        sections.append({"index":i+1,"start":round(t,3),"seconds":round(span,3),
            "end":round(t+span,3),"narration":scene_text[:400],
            "topics":topics,"match_score":score,"video":{k:v for k,v in item.items() if k!="semantic"}})
        t += span
        i += 1
    result={"episode":meta.get("slug"),"audio_duration":round(duration,3),
        "selection_method":"keyword and symbolic concept scoring; metadata-only, review recommended",
        "scenes":sections}
    write_json(output/"storyboard.json",result)
    print(f"Storyboard ready: {len(sections)} scenes; {duration:.1f}s; {len(chosen)} distinct sources",flush=True)

def fetch_video(item, cache_dir):
    uid = item["uid"]
    key = hashlib.sha256((uid + item["url"]).encode()).hexdigest()[:20]
    dest = cache_dir / (key+".mp4")
    if dest.exists():
        return dest
    tmp = dest.with_suffix(".download")
    limit = int(os.environ.get("MAX_STOCK_VIDEO_MB", "90")) * 1024 * 1024
    try:
        with requests.get(item["url"],stream=True,timeout=(20,90),
                          headers={"User-Agent":"HumanThesisVideoBuilder/1.0"}) as res:
            res.raise_for_status()
            if int(res.headers.get("content-length") or 0) > limit:
                raise ValueError(f"Source video too large ({int(res.headers.get('content-length'))//(1024*1024)} MB > {limit//(1024*1024)} MB limit)")
            size=0
            with tmp.open("wb") as f:
                for chunk in res.iter_content(1024*1024):
                    size+=len(chunk)
                    if size>limit:
                        raise ValueError("Source video exceeded download limit")
                    f.write(chunk)
        if size<10000:
            raise ValueError("Video source too small")
        seconds,w,h=ffprobe(tmp)
        if seconds < 1 or w < 640 or h < 360 or w/h < 1.38:
            raise ValueError("Video does not meet landscape/resolution constraints")
        tmp.replace(dest)
        return dest
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

def render(output):
    output=Path(output)
    plan=json.loads((output/"storyboard.json").read_text())
    scenes=plan["scenes"]
    cache=output/"source_clips"
    cache.mkdir(exist_ok=True)
    unique={s["video"]["uid"]:s["video"] for s in scenes}
    print(f"Downloading {len(unique)} unique catalog videos with 3 workers",flush=True)
    clips={}
    failed = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        pending={ex.submit(fetch_video,item,cache):uid for uid,item in unique.items()}
        for future in as_completed(pending):
            uid=pending[future]
            try:
                clips[uid]=future.result()
                print("Downloaded:",uid,flush=True)
            except Exception as exc:
                failed[uid] = str(exc)
                # A single missing/oversized source must NOT abort the film.
                print(f"Skipping unusable source {uid}: {exc}",flush=True)

    if failed:
        # Select substitute clips using the narration topics for the scene.
        # Exclude sources already known to fail; avoid pulling huge files.
        catalog = get_catalog("catalog.json")
        meta = json.loads((output/"episode.json").read_text(encoding="utf-8"))
        visuals = meta.get("visuals") or {}
        hints = visuals.get("keywords") or visuals.get("search_tags") or []
        excludes = visuals.get("avoid") or []
        if isinstance(hints,str): hints=[hints]
        if isinstance(excludes,str): excludes=[excludes]
        blocked = set(failed)
        for uid in list(failed):
            affected=[s for s in scenes if s["video"]["uid"]==uid]
            example=affected[0]
            topics=set(example.get("topics") or scene_topics(example.get("narration","")))
            success=None
            # Try a bounded number of new candidates. On any failure move on,
            # then fall back to an already-downloaded valid clip if necessary.
            for attempt in range(16):
                candidates=[v for v in catalog if v["uid"] not in blocked
                            and v["uid"] not in unique and v["uid"] not in clips]
                if not candidates:
                    break
                replacement,score=pick(candidates,topics,example.get("narration",""),
                                       list(clips),attempt,hints,excludes)
                try:
                    path=fetch_video(replacement,cache)
                    clips[replacement["uid"]]=path
                    success=(replacement,score)
                    print(f"Replaced {uid} with {replacement['uid']} (match {score})",flush=True)
                    break
                except Exception as exc:
                    blocked.add(replacement["uid"])
                    print(f"Alternative {replacement['uid']} rejected: {exc}",flush=True)
            if success is None and clips:
                # No more suitable downloadable replacements; reuse the
                # highest-scoring already verified clip rather than aborting.
                available=[v for v in catalog if v["uid"] in clips]
                if available:
                    success=pick(available,topics,example.get("narration",""),
                                 [],len(affected),hints,excludes)
                    print(f"Reusing verified stock clip for {uid}",flush=True)
            if success is None:
                raise RuntimeError(f"No usable footage available after replacing {uid}: {failed[uid]}")
            substitute,score=success
            for scene in affected:
                scene["video"]={k:v for k,v in substitute.items() if k!="semantic"}
                scene["match_score"]=score
                scene["replaced_unavailable_source"]=uid
        # Preserve the actual scene selections for future auditing.
        write_json(output/"storyboard.json",plan)
        print(f"Recovered {len(failed)} unavailable catalog sources",flush=True)
    resolution = "1280:720" if json.loads((output/"episode.json").read_text()).get("preview") else "1920:1080"
    parts=output/"segments"
    parts.mkdir(exist_ok=True)
    listing=[]
    for scene in scenes:
        src=clips[scene["video"]["uid"]]
        n=scene["index"]
        dst=parts/f"shot_{n:04}.mp4"
        # loop only when source shorter than the requested segment.
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-y",
             "-stream_loop","-1","-i",str(src),"-t",str(scene["seconds"]),
             "-vf",f"scale={resolution}:force_original_aspect_ratio=increase,crop={resolution},fps={RATE},format=yuv420p",
             "-an","-c:v","libx264","-preset","veryfast","-crf","25",
             "-movflags","+faststart",str(dst)]
        print(f"Rendering scene {n}/{len(scenes)}: {scene['topics']}",flush=True)
        command(cmd)
        listing.append(dst)
    concat=parts/"concat.txt"
    concat.write_text("".join("file '"+str(p.resolve())+"'\n" for p in listing))
    silent=output/"silent.mp4"
    command(["ffmpeg","-hide_banner","-loglevel","error","-y",
        "-f","concat","-safe","0","-i",str(concat),"-c","copy",str(silent)])
    # Subtitles are burned into video; MP3 speech is kept without time-stretching.
    final=output/"video.mp4"
    command(["ffmpeg","-hide_banner","-loglevel","error","-y",
        "-i",str(silent),"-i",str(output/"narration.mp3"),
        "-vf",f"ass={str((output/'captions.ass').resolve())}",
        "-map","0:v:0","-map","1:a:0",
        "-c:v","libx264","-preset","veryfast","-crf","23",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","160k",
        "-t",str(plan["audio_duration"]),"-movflags","+faststart",str(final)])
    final_duration, w,h=ffprobe(final)
    if abs(final_duration - plan["audio_duration"]) > 1.0:
        raise RuntimeError("Rendered video duration differs from narration")
    print(f"Rendered {w}x{h}, {final_duration:.2f}s, {final.stat().st_size/1e6:.1f}MB",flush=True)

def publish(output):
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config
    output=Path(output)
    endpoint=os.environ.get("R2_ENDPOINT") or os.environ.get("AWS_ENDPOINT_URL_S3")
    access=os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret=os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    bucket=os.environ.get("R2_BUCKET") or "human-thesis"
    if not all((endpoint,access,secret)):
        raise RuntimeError("R2 credentials missing: configure R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
    s3=boto3.client("s3",endpoint_url=endpoint,
        aws_access_key_id=access, aws_secret_access_key=secret,
        region_name="auto",config=Config(signature_version="s3v4", retries={"max_attempts":4}))
    meta=json.loads((output/"episode.json").read_text())
    name=meta["slug"]
    prefix=f"videos/{name}/{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"
    files={"video.mp4":"video/mp4","narration.mp3":"audio/mpeg",
           "captions.srt":"application/x-subrip","captions.ass":"text/plain",
           "storyboard.json":"application/json","word_timings.json":"application/json",
           "episode.json":"application/json"}
    uploaded={}
    for filename,content_type in files.items():
        src=output/filename
        key=f"{prefix}/{filename}"
        s3.upload_file(str(src),bucket,key,ExtraArgs={"ContentType":content_type},
            Config=TransferConfig(multipart_threshold=16*1024*1024,max_concurrency=4))
        s3.head_object(Bucket=bucket,Key=key)
        print(f"Verified R2 upload: {key}",flush=True)
        uploaded[filename]=key
    public=(os.environ.get("R2_PUBLIC_BASE_URL") or "").rstrip("/")
    # Signed GET links must use the S3 API hostname; a configured public domain
    # avoids signed credentials embedded in the URL entirely.
    if public:
        url=public+"/"+quote(uploaded["video.mp4"],safe="/")
        link_type="public R2 playback domain"
    else:
        # Cloudflare documents Basic GetObject presigning. Do not add
        # ResponseContentType: it can generate a signed query R2 doesn't accept.
        url=s3.generate_presigned_url("get_object",
            Params={"Bucket":bucket,"Key":uploaded["video.mp4"]},
            ExpiresIn=7*24*3600, HttpMethod="GET")
        link_type="temporary signed link (7 days); configure R2_PUBLIC_BASE_URL for permanent playback"

    # A successful upload HEAD does NOT prove the browser URL works.
    # Verify using the exact URL that appears in the published message.
    try:
        with requests.get(url, headers={"Range":"bytes=0-1023"},
                          stream=True,timeout=35,allow_redirects=True) as check:
            status=check.status_code
            if status not in (200,206):
                raise RuntimeError(f"Playback URL HTTP {status}; check public domain or signature")
            chunk=next(check.iter_content(1024),b"")
            if not chunk:
                raise RuntimeError("Playback URL returned no MP4 content")
    except Exception as exc:
        raise RuntimeError(f"R2 playback verification failed: {exc}") from None
    write_json(output/"upload.json",{"bucket":bucket,"objects":uploaded,
        "link_type":link_type,"url":url,"playback_verified":True})
    summary=os.environ.get("GITHUB_STEP_SUMMARY")
    # HTML-escape '&' to avoid GitHub interpreting ampersands in query strings.
    safe_url=html.escape(url,quote=True)
    msg=(f"## Human Thesis video ready\n\n**{meta.get('title',name)}**\n\n"
         f'<a href="{safe_url}">▶ Play verified MP4</a>\n\n'
         f"**HTTP verification:** success (200/206)\\n\\n"
         f"R2 key: \`{uploaded['video.mp4']}\`\\n\\n"
         f"Link type: {link_type}\\n\\n"
         "If GitHub masks any signed-link text, enable a public R2 domain and "
         "set the Actions variable R2_PUBLIC_BASE_URL.\\n")
    msg=msg.replace("\\n","\n")
    if summary:
        with open(summary,"a",encoding="utf-8") as f: f.write(msg)
    print("R2 upload verified. Playback link written to the GitHub Actions step summary.",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=["parse","plan","render","publish"])
    parser.add_argument("--episode",default="")
    parser.add_argument("--target",required=True)
    parser.add_argument("--catalog",default="catalog.json")
    parser.add_argument("--preview-override",default="")
    args=parser.parse_args()
    {"parse":lambda:parse_episode(args.episode,args.target,args.preview_override),
     "plan":lambda:plan(args.target,args.catalog),
     "render":lambda:render(args.target),
     "publish":lambda:publish(args.target)}[args.stage]()
