# Car Edit AI Studio

A small web app that sends short vehicle-replacement jobs to the Runway Dev Product Swap recipe.

## Current workflow

1. Upload a short source video (the provider accepts reference videos from 1.8 to 15 seconds).
2. Upload a clear photo of the original vehicle (recommended). If omitted, the app extracts a still frame from the video.
3. Upload 1–8 reference photos of the replacement vehicle.
4. Choose a 4–15 second output duration and 720p or 1080p.
5. The backend uploads the media to Runway, starts a Product Swap task, and polls its status. The provider returns a temporary MP4 URL.

## Required Render environment variables

Set these in the Render web service's Environment settings. Never put them in GitHub, HTML, or a message:

- `RUNWAY_API_KEY`: a Runway Dev API key managed by the account owner.
- `APP_ACCESS_CODE`: a long private access code chosen by the account owner. The website requires it before accepting jobs.

An adult account owner should handle provider account setup, API credentials, and any credit purchases. Each generated video may use paid provider credits. Do not share either secret with anyone.

After setting the variables, redeploy the Render service. The health endpoint reports whether both values are configured without revealing them.

## Important limitations

- This is an early integration, not a finished production service.
- The Runway Product Swap recipe accepts reference videos from 1.8 to 15 seconds and output durations from 4 to 15 seconds.
- The original-vehicle photo matters. The automatically extracted frame may not show the vehicle clearly.
- Job records are held in server memory and can be lost if the free Render instance restarts.
- Provider output links are temporary (typically 24–48 hours); download the result promptly.
- There is no user account system, durable file storage, payment protection, or usage quota yet. Keep the site private by keeping the access code secret.
- The app currently supports 100 MB source videos and 8 MB per image to avoid overloading the small web service.

## Run locally

Install dependencies from `backend/requirements.txt`, ensure FFmpeg is installed, set both environment variables, then run:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 10000
```
