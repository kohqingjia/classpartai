# Deployment

This template is **opinionated towards [Bun](https://bun.sh/)**. It builds with [Nitro](https://nitro.build/) using the `preset: "bun"` configuration and runs on Bun (`oven/bun:1-alpine`) in both development and production containers. Runtime code uses Bun-native APIs (`bun:sql`, `Bun.s3`, and `Bun.RedisClient`).

## Changing the deployment target

The default target is Bun. If you wish to target a different platform, set the Nitro preset in `vite.config.ts`:

```ts
nitro({
  preset: "bun", // default
  rollupConfig: { external: ["bun", /^bun:/, /^@sentry\//] },
}),
```

Or set the `NITRO_PRESET` environment variable at build time instead of editing the file.

> [!NOTE]
> **Bun-Native Portability**: Because this template is opinionated towards Bun, runtime features rely on Bun's built-in APIs (`bun:sql`, `Bun.s3`, `Bun.RedisClient`). Any container platform (Docker, AWS ECS/Fargate, GCP Cloud Run, Azure Container Apps, Railway, Fly.io, Render) runs the Bun container without modification. If targeting non-Bun serverless environments (such as Node-only Vercel functions or Cloudflare Workers), replace the Bun-native drivers with platform-specific alternatives (e.g. `@neondatabase/serverless` for Postgres, `@aws-sdk/client-s3` for S3, or `@upstash/redis` for Redis).

---

## Platforms

### Docker / Bun (default)

The included `Dockerfile` and `docker-compose.yaml` cover this. No preset change needed — Nitro builds with `preset: "bun"` and the container runs `bun --bun .output/server/index.mjs` on port 3000.

```bash
docker build -t my-app .
docker run -p 3000:3000 --env-file .env my-app
```

Works on any platform that runs containers: AWS ECS/Fargate, Azure Container Apps, GCP Cloud Run, Railway, Fly.io, Render, etc. See the platform-specific sections below for environment and port config.

---

### Vercel

Nitro auto-detects Vercel from the build environment — no preset change needed in most cases. If you need to force it:

```ts
nitro({ preset: "vercel" });
```

**Database**: Vercel runs serverless functions with short-lived connections. Add a connection pooler in front of Postgres: [Neon](https://neon.tech/) (built-in pooling), [Supabase](https://supabase.com/) (pgBouncer), or [PgBouncer on Railway](https://railway.app/).

**Environment variables**: Set all `.env` values in the Vercel dashboard under Settings → Environment Variables.

---

### Cloudflare Pages / Workers

```ts
nitro({ preset: "cloudflare-pages" });
```

Build output goes to `.output/` and is deployed via [Wrangler](https://developers.cloudflare.com/workers/wrangler/):

```bash
bun run build
npx wrangler pages deploy .output/public
```

**Edge runtime limitations** — Cloudflare Workers runs on V8, not Bun or Node.js. The following do not work without substitution:

| Component          | Issue                                      | Fix                                                                                                                             |
| ------------------ | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `bun:sql`          | Bun-native SQL driver requires Bun runtime | Use [Neon serverless driver](https://neon.tech/docs/serverless/serverless-driver) (`@neondatabase/serverless`) or Supabase REST |
| `Bun.s3`           | Native Bun S3 client requires Bun runtime  | Use `@aws-sdk/client-s3` or HTTP PUT fetch                                                                                      |
| Better Auth        | Uses `process.platform` and Node.js crypto | Not yet edge-compatible; pin to a Node.js/Bun target or use Cloudflare Workers Node.js compatibility flags (`nodejs_compat`)    |
| File system access | Not available                              | Already handled — storage uses S3 presigned URLs                                                                                |

For a Cloudflare deployment with a compatible database, Neon is the simplest path: replace the `drizzle-orm/bun-sql` driver with `drizzle-orm/neon-serverless`.

---

### AWS Lambda

```ts
nitro({ preset: "aws-lambda" });
```

The build output is a Lambda-compatible handler. Deploy behind API Gateway (HTTP API or REST API):

1. `bun run build` — produces `.output/server/index.mjs`
2. Zip and upload the `.output/` directory to Lambda, or use a deployment tool (SST, AWS CDK, Serverless Framework).
3. Set the handler to `index.handler`.

**Database**: Same as Vercel — use a connection pooler (RDS Proxy, Neon, or PgBouncer) to avoid exhausting Postgres connections under load.

**Environment variables**: Set via Lambda environment configuration or SSM Parameter Store.

---

### GCP Cloud Run

No preset change — use the Docker deployment path.

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/my-app
gcloud run deploy my-app \
  --image gcr.io/PROJECT_ID/my-app \
  --port 3000 \
  --set-env-vars DATABASE_URL=...,BETTER_AUTH_SECRET=...
```

Cloud Run scales to zero and auto-scales under load. Use [Cloud SQL](https://cloud.google.com/sql) with the Cloud SQL Auth Proxy sidecar, or use a Postgres SaaS (Neon, Supabase) that accepts connections from Cloud Run's egress IPs.

---

### Azure Container Apps

No preset change — Docker deployment.

```bash
az acr build --registry myregistry --image my-app .
az containerapp create \
  --name my-app \
  --resource-group my-rg \
  --environment my-env \
  --image myregistry.azurecr.io/my-app \
  --target-port 3000 \
  --ingress external \
  --env-vars DATABASE_URL=... BETTER_AUTH_SECRET=...
```

Use Azure Database for PostgreSQL (Flexible Server) or a Postgres SaaS. Secrets should go through Azure Key Vault references rather than plain env vars.

---

### Netlify

```ts
nitro({ preset: "netlify" });
```

Netlify also auto-detects this from the build environment. Same edge runtime limitations as Cloudflare if you use `netlify-edge` — stick with `netlify` for standard Node.js Lambda execution.

---

## Storage and email across environments

**MinIO / S3**: Set `MINIO_ENDPOINT` to your S3-compatible endpoint. Powered by Bun's native `S3Client` (`Bun.s3`). For AWS S3 use `https://s3.amazonaws.com`, for Cloudflare R2 use your R2 endpoint, for Supabase Storage use `https://<project>.supabase.co/storage/v1/s3`. Bucket, access key, and secret key follow the same env vars regardless of provider.

**Resend**: Works everywhere — it's an HTTP API. Set `RESEND_API_KEY` and `EMAIL_FROM`.

**Redis**: Set `REDIS_URL` (e.g. `redis://localhost:6379`). Bun's native Redis client (`Bun.RedisClient`) connects directly to Redis/Valkey instances without intermediary HTTP proxies.

**Sentry**: Set `VITE_SENTRY_DSN`. The plugin only runs source map uploads at build time when `SENTRY_AUTH_TOKEN` is set; runtime error capture works from the DSN alone.

---

## Database migrations in production

Before starting a new application release or as part of your CI/CD deployment pipeline, apply pending migrations against your production database:

```bash
bun run db:migrate
```

This applies unapplied SQL migrations from `src/db/drizzle/` in sequential order using Drizzle Kit. Avoid using `db:push` in production environments as it does not record migration history.
