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


## Generate YouTube narration (committed to this repo)

**Actions → Generate cinematic narration → Run workflow**. The default `scripts/demo.txt` is a reflective Stoic voice test. Set `preview=true` (recommended) to create a short sample first. Choose `speed=0.88` and the voice design attributes `male, middle-aged, low pitch, american accent`; these are supported VoiceStudio attributes, not a guaranteed particular actor's voice.

To produce a full audiobook-style narration, create a UTF-8 text file under `scripts/` (for example `scripts/jung-summary.txt`) and enter that path in the workflow. Set `preview=false`. The generator divides the script into smaller requests, synthesizes them sequentially, combines the audio, and compresses it to 64 kbps mono MP3.

Instead of uploading a GitHub Actions artifact, the workflow commits to `generated/<run_id>-<attempt>/` on the current branch:
- `narration.mp3`: synthesized narration
- `script.txt`: exact text used (preview truncates to ~500 characters)
- `manifest.json`: voice parameters and approximate duration

**Important limitations:** GitHub is not intended for large generated-media storage. Each file must stay below 100 MB, and repeated commits expand repository history permanently. A 30-minute mono 64 kbps MP3 is roughly 14 MB; use object storage when the narrator configuration is established. A GitHub-hosted CPU may also be too slow for 20–30-minute production. WAV/MP3 generation has not yet been verified with these long scripts. The voice-design tags may need refinement or a **licensed, clean reference recording** (via an upcoming configuration) to achieve consistently human, soft, deep narration. Each run creates a fresh temporary API key; no repository secret is needed.

### GPU notes

For supported Linux NVIDIA hosts, follow the upstream instructions for the NVIDIA Container Toolkit and add the Compose GPU reservation/device configuration suited to your host. Default config is intended for CPU operation.

### Licensing

VoiceStudio source is AGPL-3.0. Model weights and voices may have separate usage terms. Use only voice samples you have permission to clone.

Upstream docs: [Docker installation](https://github.com/debpalash/VoiceStudio/blob/main/docs/install/docker.md).
