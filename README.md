# VoiceStudio — Docker runner

This repository provides a simple, **unofficial deployment wrapper** for [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio), not a copy of its application source. It uses the maintainer's published `ghcr.io/debpalash/voicestudio:stable` image.

## Run on your machine or a Linux server

Requires Docker Engine with the Compose plugin, sufficient RAM, disk space for speech models, and an x86-64 host (for this image).

1. Copy `.env.example` to `.env`.
2. Replace `OMNIVOICE_API_KEY` with a strong random secret. On Linux/macOS: `openssl rand -hex 32`.
3. Start VoiceStudio:

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

Open **http://localhost:3900** on the same machine. The browser will request your administrator key. Voice models may download separately on first use.

Stop: `docker compose down`. Upgrade: `docker compose pull && docker compose up -d`.

### Remote server access

The Compose port deliberately binds to `127.0.0.1` for safety. On a remote Linux host, use SSH port forwarding from your PC:

```bash
ssh -L 3900:127.0.0.1:3900 USER@YOUR_SERVER
```

Then open http://localhost:3900 locally. Do not expose the API to the public internet without a properly secured HTTPS reverse proxy and access controls.

### GitHub Actions

Open **Actions → VoiceStudio Docker smoke test → Run workflow**. The workflow downloads the official image, starts the web service, checks the HTTP response, prints diagnostics, then removes the container. This is **only a temporary test**, not persistent hosting; it does not synthesize speech or verify model inference. Hosted runners may lack disk/RAM for the image.

To host VoiceStudio continuously, use Docker on your own computer, a dedicated server, or a machine with an appropriate GPU. Vercel's serverless functions and GitHub-hosted Actions are not suited to an always-running GPU speech application.


## YouTube narration: Kokoro George (selected voice)

The narration workflow now uses **Kokoro-82M / bm_george**, a British English male preset. This is the exact **voice ID** chosen from the Colab audition; output uses the same **0.90 speed** default. The earlier VoiceStudio Docker smoke test remains available separately.

**Use:** [Actions → Generate Kokoro George narration](../../actions/workflows/generate-audio.yml) → Run workflow.

- `script_path`: a UTF-8 .txt inside `scripts/` (default: `scripts/demo.txt`)
- `preview=true`: read only the first approximately 500 characters (test first)
- `preview=false`: narrate the whole text, including long YouTube scripts
- `speed=0.90`: the selected Colab pacing

The generator works in bounded sections to avoid loading a whole audiobook in memory and adds 0.3-second section / 0.6-second paragraph pauses. Audio is encoded as mono **96 kbps MP3**. The GitHub Actions run commits `generated/<run-id>-<attempt>/narration.mp3`, `script.txt`, and `manifest.json` directly to the repository. **No GitHub Actions artifacts** or API keys are needed for the narrator workflow.

For a new episode, add a file such as `scripts/machiavelli-summary.txt`, then run the workflow with that path. Preview first.

**Limitations:** GitHub Actions has no dedicated GPU and synthesis of a 20–30-minute video may be slow or hit runner limits. Git commits are a temporary output store: MP3 files accumulate permanently in repo history and files larger than 100 MB are rejected (our safety cap is 95 MB). Later we can switch the destination to object storage. The model may still make pronunciation mistakes or vary slightly at chunk boundaries.

### GPU notes

For supported Linux NVIDIA hosts, follow the upstream instructions for the NVIDIA Container Toolkit and add the Compose GPU reservation/device configuration suited to your host. Default config is intended for CPU operation.

### Licensing

VoiceStudio source is AGPL-3.0. Model weights and voices may have separate usage terms. Use only voice samples you have permission to clone.

Upstream docs: [Docker installation](https://github.com/debpalash/VoiceStudio/blob/main/docs/install/docker.md).

## Word-synchronized subtitles (new)

The **Generate Kokoro George narration** workflow now creates three additional files beside `narration.mp3`:

- `captions.ass`: cinematic, centered just below midpoint (1920×1080 coordinates 960,735); warm-gold karaoke progress, clear text and translucent charcoal backing. Works when burned into video with FFmpeg/libass.
- `captions.srt`: regular captions for YouTube upload/accessibility (no word highlighting).
- `word_timings.json`: timestamped words and grouped cues for the future background-video/caption compositor.

Caption times are estimated **from the finished MP3** with faster-whisper `small.en`, *not* calculated from the script. This preserves George's actual pauses. Please review the results—Whisper may mishear names or create timings errors. The model is cached using `actions/cache` to avoid repeatedly downloading it, but cache availability and retention are controlled by GitHub. The large Kokoro voice/model is cached through Hugging Face only when configured; the current setup downloads Kokoro weights each fresh runner invocation.

### Future input format

See [`input/EPISODE_TEMPLATE.txt`](input/EPISODE_TEMPLATE.txt) for the proposed episode metadata: title, alternate titles, description, tags, narration voice/speed/pauses, visual concepts and exclusions, captions, thumbnail brief, output resolution and preview. **The existing workflow does not yet trigger on input-folder changes or parse this format.** For now place narration-only text under `scripts/*.txt` and manually run the workflow. The input template is a specification for the next stage, not an active automation.

Note: this repository does not currently contain `catalog.json`, so visual-selection integration is not active yet.
