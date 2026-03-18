# GCP Deployment (GitHub Actions → Cloud Run)

This repo ships with GitHub Actions workflows to deploy the **Memories API** service to **Cloud Run** using **Workload Identity Federation** (OIDC) from GitHub (no long-lived JSON keys).

## What gets deployed

- Cloud Run service: `memory_service` (FastAPI), using `uvicorn` with `memory_service.asgi:app`.

If you want to deploy other services (Discord bot, ingestion poller, Matrix adapter), you should deploy them as Cloud Run **Jobs** or on GKE/VMs; they are not wired up by default.

## 1) GCP prerequisites

Enable APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com
```

Create an Artifact Registry Docker repo (pick your region, e.g. `us-central1`):

```bash
gcloud artifacts repositories create bibliotalk \
  --repository-format=docker \
  --location=us-central1
```

## 2) Create GitHub → GCP Workload Identity Federation

Pick:
- `POOL=bibliotalk-github`
- `PROVIDER=github`
- `SA=github-deployer`
- `PROJECT_ID=...`
- `PROJECT_NUMBER=...`
- `GITHUB_OWNER=...`
- `GITHUB_REPO=...`

You can fetch the project number via:

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
```

Create the pool:

```bash
gcloud iam workload-identity-pools create "$POOL" \
  --location="global" \
  --display-name="GitHub Actions pool"
```

Create the provider:

```bash
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --location="global" \
  --workload-identity-pool="$POOL" \
  --display-name="GitHub Actions OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="attribute.repository=='${GITHUB_OWNER}/${GITHUB_REPO}'"
```

Create a deployer service account:

```bash
gcloud iam service-accounts create "$SA" --display-name="GitHub deployer"
```

Grant it permissions (adjust as needed; this is a typical baseline for Cloud Run + Artifact Registry):

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

Allow GitHub to impersonate that service account:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  "${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_OWNER}/${GITHUB_REPO}"
```

Get the provider resource name (needed by GitHub Actions):

```bash
gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --location=global \
  --workload-identity-pool="$POOL" \
  --format="value(name)"
```

## 3) Configure GitHub repo variables/secrets

Set these GitHub **Repository Variables** (Settings → Secrets and variables → Actions → Variables):

- `GCP_PROJECT_ID` (e.g. `my-project`)
- `GCP_REGION` (e.g. `us-central1`)
- `GCP_ARTIFACT_REPO` (e.g. `bibliotalk`)
- `CLOUD_RUN_SERVICE` (e.g. `bibliotalk-memories`)
- `GCP_WORKLOAD_IDENTITY_PROVIDER` (the full provider name from step 2)
- `GCP_SERVICE_ACCOUNT` (e.g. `github-deployer@my-project.iam.gserviceaccount.com`)

Optional variables:

- `CLOUD_RUN_ENV_VARS` (comma-separated `KEY=VALUE` pairs for non-secrets)
- `CLOUD_RUN_SECRETS` (comma-separated `KEY=SECRET_NAME:VERSION` pairs; uses Secret Manager)

## 4) Deploy

- Push to `main` to deploy automatically, or run the workflow manually:
  - GitHub Actions → run the Cloud Run deploy workflow → Run workflow

## Notes / gotchas

- Cloud Run is **stateless**; the current codebase uses **SQLite**. A Cloud Run instance restart will lose local DB state unless you provide persistence (recommended: move to Postgres/Cloud SQL; the codebase does not yet support it).
