# My Jersey Frame Forge AI Engine

Lightweight, private orchestration engine for template-driven mockup creation and optional 10–30 second advertisement videos. All AI analysis, image generation, and video generation route through OpenRouter. Exact logo and contact details are composited locally after generation so the model cannot misspell or redesign them.

## Workflow

1. Upload a visual source and optional brand logo.
2. Select one of three mockup templates.
3. Select Quality or Cost-Effective mode and an aspect ratio.
4. OpenRouter analyzes the source, then the selected template prompt is combined with the analysis and user direction.
5. The OpenRouter Image API creates the mockup from normalized reference images.
6. Frame Forge adds the exact supplied logo and contact footer.
7. The user downloads the mockup or continues to one of three video templates.
8. Duration selects the configured short, medium, or long OpenRouter video model pool. The OpenRouter Video API runs asynchronously, Frame Forge polls it, downloads the MP4, and applies exact branding with FFmpeg.

The frontend never receives the OpenRouter key.

## Included templates

### Mockup

- `mockup_luxury_float` — ultra-realistic floating 3D product advertisement.
- `mockup_stadium_hero` — premium floodlit stadium campaign.
- `mockup_editorial_launch` — clean fashion/editorial launch campaign.

### Video

- `video_luxury_360` — smooth 360-degree studio rotation.
- `video_stadium_reveal` — tunnel-to-stadium hero reveal.
- `video_kinetic_social` — polished fast-cut social advertisement.

Each template has a bundled SVG preview exposed by the template catalog.

## Modes and model selection

Quality and Cost-Effective are real, independently configured routes—not UI labels. Each mode has ordered fallback lists for:

- visual analysis;
- image generation;
- short video (10–12 seconds);
- medium video (13–20 seconds);
- long video (21–30 seconds).

OpenRouter video models support different duration, resolution, aspect-ratio, and frame-image combinations. Configure each pool only with current OpenRouter model IDs that support its intended requests. If a candidate explicitly rejects the request, Frame Forge tries the next configured candidate. If a submission has an ambiguous network outcome, it stops instead of automatically spending credits twice.

The bundled `.env.example` contains capability-matched recommendations verified against the OpenRouter catalog on 2026-10-30. They remain environment settings, not hardcoded application behavior. The video API does not currently expose native `4:5`; Frame Forge requests the nearest `3:4` provider ratio and then performs a deterministic centered crop to the user-selected `4:5` output before branding.

## Supported inputs

Primary source:

- PNG, JPEG, WebP, GIF;
- SVG (active/external content is rejected);
- PDF (first page is rendered as the visual reference);
- EPS/PostScript (first page through sandboxed Ghostscript);
- PSD (first composite frame through Pillow).

Logo:

- PNG, JPEG, or WebP.

All primary sources are normalized to a bounded PNG reference before being sent to OpenRouter. Source contents are treated as untrusted visual data, not prompt instructions.

## API

```text
GET  /api/healthz
GET  /api/frameforge/capabilities
GET  /api/frameforge/templates
GET  /api/frameforge/templates/{template_id}/preview.svg

POST /api/frameforge/jobs/mockup
POST /api/frameforge/jobs/{mockup_job_id}/video
GET  /api/frameforge/jobs/{job_id}
POST /api/frameforge/jobs/{job_id}/cancel
GET  /api/frameforge/jobs/{job_id}/output
```

All routes except health, static previews, and short-lived signed provider assets require:

```http
Authorization: Bearer <FRAMEFORGE_ENGINE_TOKEN>
```

### Create mockup

`POST /api/frameforge/jobs/mockup` uses multipart fields:

- `source` — required visual source;
- `logo` — optional raster logo;
- `options_json` — JSON matching this example:

```json
{
  "template_id": "mockup_luxury_float",
  "mode": "quality",
  "aspect_ratio": "9:16",
  "style_notes": "Use a blue-black premium campaign mood",
  "brand": {
    "brand_name": "My Jersey",
    "tagline": "Built for Champions",
    "phone": "+8801XXXXXXXXX",
    "email": "hello@example.com",
    "website": "example.com",
    "address": "Rajshahi, Bangladesh",
    "social_handle": "@myjersey"
  }
}
```

### Create video from completed mockup

```http
POST /api/frameforge/jobs/{mockup_job_id}/video
Content-Type: application/json

{
  "template_id": "video_luxury_360",
  "mode": "quality",
  "aspect_ratio": "9:16",
  "duration_seconds": 20,
  "style_notes": "Slow premium motion with a strong final hero frame"
}
```

The API returns `202` immediately. Poll the returned job ID until `ready`, then use its `download_url`.

## OpenRouter contract

- Analysis: `POST /api/v1/chat/completions`
- Mockups: `POST /api/v1/images` with `input_references`
- Videos: `POST /api/v1/videos`, followed by the returned `polling_url`
- Completed video: authenticated OpenRouter content URL or job content endpoint

Video generation requires OpenRouter to retrieve the approved first-frame image. Frame Forge exposes only that image through an expiring HMAC-signed HTTPS URL. Configure `FRAMEFORGE_PUBLIC_BASE_URL` to the public Railway hostname and use a separate strong `FRAMEFORGE_ASSET_SIGNING_SECRET`.

## Deployment

Copy `.env.example` into Railway variables and set all secrets/model pools. Deploy with the included `Dockerfile`; it installs FFmpeg, Ghostscript, Cairo, and Noto fonts required for deterministic media processing. `railpack.json` is also included for environments where the required native packages are already available.

The health endpoint reports whether each mode is fully configured without exposing URLs, model names, or secrets.

## Storage and restart safety

- Job files are temporary and cleaned after `FRAMEFORGE_RETENTION_HOURS`.
- Downloads use `Cache-Control: no-store`.
- A restart never silently resubmits a paid request. Interrupted jobs are marked failed with `ENGINE_RESTARTED` so provider history can be checked first.
- Provider-returned external URLs are rejected unless their HTTPS hostname is explicitly allowlisted.
- The service refuses a public bind without `FRAMEFORGE_ENGINE_TOKEN`.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install '.[test]'
cp .env.example .env
python -m pytest
python -m frameforge_engine.server
```

No live generation test runs without an OpenRouter key and explicitly configured model pools; the automated suite uses deterministic fakes and does not spend credits.

