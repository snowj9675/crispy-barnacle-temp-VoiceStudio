# Human Thesis full video production

The new workflow, **Produce Human Thesis video to R2**, is triggered when a `input/*.md` file changes on the default branch, or manually from GitHub Actions. It performs:

1. Parses YAML episode metadata and extracts narration only.
2. Synthesizes using Kokoro `bm_george`, speed `0.90`, preserving existing section/paragraph pauses.
3. Runs faster-whisper on the actual narration MP3 for SRT, ASS karaoke and word-level JSON.
4. Chooses a 12-second landscape shot for each audio interval from `catalog.json`, using script concepts and metadata matching.
5. Downloads matched videos concurrently (3 downloads at a time), verifies their format and aspect ratio, and renders a video with burned captions.
6. Uploads MP4, narration, captions and storyboard to Cloudflare R2 with verification.
7. Writes a streaming link to the workflow **Step summary** (public URL when `R2_PUBLIC_BASE_URL` is configured; otherwise a temporary signed link, valid for 7 days).

Audio and video are not uploaded as GitHub Actions artifacts in this pipeline. The original narration-only workflow remains available independently.

## GitHub Actions secrets and variables

Set **Actions secrets** in the repository (or the GitHub Environment named `production`):

- `R2_ACCESS_KEY_ID` — R2 S3 API key ID.
- `R2_SECRET_ACCESS_KEY` — R2 S3 API secret.
- `R2_ENDPOINT` — R2 S3 endpoint, for example `https://<account>.r2.cloudflarestorage.com`.
- `R2_BUCKET` — `human-thesis`, optional since it is the workflow default.

Alternative names `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`, `ENDPOINT`, `BUCKET` are also accepted. `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are accepted for credentials.

Optional **Actions variable** `R2_PUBLIC_BASE_URL`: your bucket's *public* r2.dev domain or custom domain, e.g. `https://example.r2.dev`. The S3 API endpoint is NOT a public playback address. Without a public domain, an R2 presigned URL is placed in the run summary and expires after 7 days.

If environment-level secrets are stored under a different GitHub Environment, set repository **Actions variable** `R2_ENVIRONMENT` to that environment name. Do not paste actual R2 credentials into episode files or committed source.

## Episode input

Create a new Markdown file in `input/`, e.g. `input/my-new-video.md`:

```md
---
title: The Quiet Power of Self Awareness
slug: the-quiet-power
preview: true
voice:
  speed: 0.90
visuals:
  keywords: [loneliness, shadow, mirror, philosophy, introspection]
  avoid: [beach, swimwear, glamour, fashion]
  scene_seconds: 12
thumbnail:
  headline: KNOW YOUR SHADOW
  concept: A lone silhouette beside a dark mirror
description: Deep reflections on awareness and freedom.
tags: [Carl Jung, stoicism, psychological independence]
---

There is a kind of silence that changes everything...

The Stoics understood the value of restraint...
```

`preview: true` produces a short test using the first ~500 narration characters at 1280×720. Set `preview: false` for the full narration at 1920×1080. The `voice.speed` field controls the selected narrator. **Do not put non-spoken instructions in the narration body**.

The workflow will process each new or changed `.md` file found in a commit to `input/`. It does not generate the thumbnail yet; thumbnail instructions are carried in episode metadata for future implementation.

## Editorial safety / relevance

Selection uses transcript topics and catalog descriptions/categories, then rejects explicit off-theme metadata (beach, swimwear, glamour and similar). **It cannot guarantee on-screen visual appropriateness**: the catalog's metadata has not been verified frame-by-frame. Review the storyboard and final test video before publishing on YouTube. The footage matcher produces a reproducible scene plan in `storyboard.json` so wrong selections can be diagnosed.

## Practical capacity

The first job may download Kokoro and Whisper model files; GitHub cache attempts to preserve model weights across workflows, subject to GitHub cache eviction/limits. Full 1080p rendering is CPU intensive and may exceed GitHub-hosted runner time/disk limits. Our initial test deliberately uses a short preview. R2 objects are uploaded with `video/mp4` content type and faststart metadata for browser playback.
