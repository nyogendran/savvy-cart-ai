# Deploy to Cloud Run

The service is the FastAPI app in `src/savvycart/http.py`, built from the repo's `Dockerfile` and served by uvicorn on port 8080.

| Setting | Value |
| --- | --- |
| Service name | `savvy-cart` |
| Region | `asia-southeast1` |
| Minimum instances | `--min-instances=0` (scale to zero) |
| Request timeout | `--timeout=120` |
| Access | `--allow-unauthenticated` (guest judge path, no login) |
| Container port | `8080` |

The first request after an idle period may be slow, often tens of seconds, while Cloud Run starts an instance from zero. This is expected with minimum instances at 0.

If the chosen Gemini model is not callable from `asia-southeast1`, deploy to the region where it works and name that region in `README.md`.

## Configuration and secrets

`GEMINI_MODEL` and the model API key come from Secret Manager or the Cloud Run environment at deploy time, never from the `Dockerfile` or this document. Without them the app still serves the full sample path, and **Extract this image** reports that the live extract failed.

1. Store the key once in Secret Manager. Read it from a prompt so it never lands in shell history:

   ```bash
   gcloud secrets create gemini-api-key --replication-policy=automatic
   read -rs GEMINI_KEY && printf '%s' "$GEMINI_KEY" | gcloud secrets versions add gemini-api-key --data-file=- && unset GEMINI_KEY
   ```

2. Grant the Cloud Run runtime service account `roles/secretmanager.secretAccessor` on that secret.

3. Deploy from the repo root. Replace `<model-id>` with the model you chose; the project comes from your active gcloud configuration, not from this repo:

   ```bash
   gcloud run deploy savvy-cart \
     --source . \
     --region asia-southeast1 \
     --port 8080 \
     --min-instances=0 \
     --timeout=120 \
     --allow-unauthenticated \
     --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
     --set-env-vars GEMINI_MODEL=<model-id>
   ```

4. Read the service URL and put it at the top of the judge path in `README.md`:

   ```bash
   gcloud run services describe savvy-cart --region asia-southeast1 --format='value(status.url)'
   ```

## Keep-alive window (19 Oct – 6 Nov 2026)

- Keep `--min-instances=0`. A cold start is acceptable; a warm instance for the whole window is not worth paying for.
- Set a billing budget alert on the project.
- Redeploy only to restore a broken sample path, on the same service and URL.

The image excludes tests, ADLC evidence, real receipt photos, and any JSON key file (see `.dockerignore`).
