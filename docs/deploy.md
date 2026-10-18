# Deploy to Cloud Run

The service is the FastAPI app in `src/savvycart/http.py`, built from the repo's `Dockerfile` and served by uvicorn on port 8080.

| Setting | Value |
| --- | --- |
| Service name | `savvy-cart` |
| Region | `asia-southeast1` |
| Minimum instances | `--min-instances=0` (scale to zero) |
| Maximum instances | `--max-instances=3` (the model rate limits are per instance, so this caps Gemini cost on a public URL) |
| Request timeout | `--timeout=120` |
| Access | `--allow-unauthenticated` (guest judge path, no login) |
| Container port | `8080` |

The first request after an idle period may be slow, often tens of seconds, while Cloud Run starts an instance from zero. This is expected with minimum instances at 0.

If the chosen Gemini model is not callable from `asia-southeast1`, deploy to the region where it works and name that region in `README.md`.

## Configuration and secrets

Gemini runs on Gemini Enterprise Agent Platform (formerly Vertex AI). The Cloud Run service account authenticates with Application Default Credentials, so the default deploy has **no API key**. Secret Manager holds the model configuration (`GEMINI_MODEL`), mounted at deploy time. Nothing in the `Dockerfile` or this document is a secret, and no project id is written here. Without a configured model the app still serves the full sample path; **Extract this image** reports that the live extract failed and **Explain this plan** shows the engine explanation.

Set shell variables first. `PROJECT_ID` is your project; the values stay in your shell, not in git:

```bash
PROJECT_ID=$(gcloud config get-value project)
SA=savvy-cart-run@${PROJECT_ID}.iam.gserviceaccount.com
```

1. Enable the APIs:

   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
     secretmanager.googleapis.com aiplatform.googleapis.com
   ```

2. Create the runtime service account and let it call Gemini on Agent Platform:

   ```bash
   gcloud iam service-accounts create savvy-cart-run --display-name "Savvy Cart Cloud Run runtime"
   gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role roles/aiplatform.user
   ```

3. Store the model id in Secret Manager and let the runtime read it. Pick a Gemini model available on Agent Platform; the id is configuration, not code:

   ```bash
   printf '%s' "<model-id>" | gcloud secrets create savvy-cart-gemini-model --replication-policy=automatic --data-file=-
   gcloud secrets add-iam-policy-binding savvy-cart-gemini-model --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor
   ```

4. Source deploys build with the default compute service account. On a new project it needs the Cloud Run builder role:

   ```bash
   PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
   gcloud projects add-iam-policy-binding "$PROJECT_ID" \
     --member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" --role roles/run.builder
   ```

5. Deploy from the repo root:

   ```bash
   gcloud run deploy savvy-cart \
     --source . \
     --region asia-southeast1 \
     --port 8080 \
     --min-instances=0 \
     --max-instances=3 \
     --timeout=120 \
     --allow-unauthenticated \
     --service-account "$SA" \
     --set-secrets GEMINI_MODEL=savvy-cart-gemini-model:latest \
     --set-env-vars GOOGLE_GENAI_USE_ENTERPRISE=true,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=global
   ```

   `GOOGLE_CLOUD_LOCATION` is where the model is called, separate from the Cloud Run region. `global` serves current Gemini models; use `asia-southeast1` instead if your model is offered there.

6. Read the service URL and put it at the top of the judge path in `README.md`:

   ```bash
   gcloud run services describe savvy-cart --region asia-southeast1 --format='value(status.url)'
   ```

### Alternative: Gemini Developer API key

If you use an API key instead of Agent Platform, store it in Secret Manager from a hidden prompt so it never lands in shell history, grant the runtime `roles/secretmanager.secretAccessor` on it, and replace the enterprise variables with the key:

```bash
gcloud secrets create gemini-api-key --replication-policy=automatic
read -rs GEMINI_KEY && printf '%s' "$GEMINI_KEY" | gcloud secrets versions add gemini-api-key --data-file=- && unset GEMINI_KEY
# deploy with: --set-secrets GEMINI_MODEL=savvy-cart-gemini-model:latest,GEMINI_API_KEY=gemini-api-key:latest
```

## Live checks after deploy

Run these once against the configured model (same environment variables as the service) and note the model id and timings in the README:

```bash
python scripts/extract_receipt_live.py      # receipt photo -> lines, compared with the transcription
python scripts/read_offer_live.py           # sample bank offer text -> terms, compared with the checked-in reading
```

Then on the live URL: **Use sample receipt**, **Upload a receipt photo**, **Check a card offer** → **Read it with Gemini**, and a question on the **Why** step.

## Keep-alive window (19 Oct – 6 Nov 2026)

- Keep `--min-instances=0`. A cold start is acceptable; a warm instance for the whole window is not worth paying for.
- Set a billing budget alert on the project.
- Redeploy only to restore a broken sample path, on the same service and URL.

The image excludes tests, ADLC evidence, real receipt photos, and any JSON key file (see `.dockerignore`).
