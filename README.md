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

### GPU notes

For supported Linux NVIDIA hosts, follow the upstream instructions for the NVIDIA Container Toolkit and add the Compose GPU reservation/device configuration suited to your host. Default config is intended for CPU operation.

### Licensing

VoiceStudio source is AGPL-3.0. Model weights and voices may have separate usage terms. Use only voice samples you have permission to clone.

Upstream docs: [Docker installation](https://github.com/debpalash/VoiceStudio/blob/main/docs/install/docker.md).
