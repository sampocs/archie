// The Railway project `archie` (environment `production`). Preview with `railway config plan`, apply with
// `railway config apply`. Values held as preserve() stay in Railway: the repo is public, so secrets and the owner's
// email never live here. Generated *.up.railway.app domains can't be declared; see docs/deploy.md.
import { defineRailway, github, image, preserve, project, service, volume } from "railway/iac";

const REGION = "us-east4-eqdc4a";
const PG_DATA_MOUNT = "/var/lib/postgresql/data";

export default defineRailway(() => {
  const postgresVolume = volume("postgres-volume", {
    alerts: { usage: { "100": {}, "80": {}, "95": {} } },
    allowOnlineResize: true,
    region: REGION,
    sizeMB: 5000,
  });

  // Railway's standard Postgres image has no pgvector, and migration 0001 runs CREATE EXTENSION vector.
  // The major version must stay 18: the volume holds a PG 18 data directory.
  const Postgres = service("Postgres", {
    source: image("pgvector/pgvector:pg18"),
    replicas: { [REGION]: 1 },
    deploy: { requiredMountPath: PG_DATA_MOUNT },
    networking: { privateNetworkEndpoint: "postgres" },
    volumeMounts: { [PG_DATA_MOUNT]: postgresVolume },
    env: {
      POSTGRES_USER: "postgres",
      POSTGRES_PASSWORD: preserve(),
      POSTGRES_DB: "railway",
      // initdb refuses a non-empty directory, and the volume root holds lost+found.
      PGDATA: `${PG_DATA_MOUNT}/pgdata`,
      PGHOST: "${{RAILWAY_PRIVATE_DOMAIN}}",
      PGPORT: "5432",
      PGUSER: "${{POSTGRES_USER}}",
      PGPASSWORD: "${{POSTGRES_PASSWORD}}",
      PGDATABASE: "${{POSTGRES_DB}}",
      DATABASE_URL: "postgresql://${{PGUSER}}:${{POSTGRES_PASSWORD}}@${{RAILWAY_PRIVATE_DOMAIN}}:5432/${{PGDATABASE}}",
      RAILWAY_DEPLOYMENT_DRAINING_SECONDS: "60",
    },
  });

  // One container: migrations, then the API and the worker (archie-launch).
  const archie = service("archie", {
    // checkSuites: deploy a commit only after its GitHub Actions checks pass.
    source: github("sampocs/archie", { branch: "main", checkSuites: true }),
    // Railway builds the root Dockerfile without being told to, and restarts on failure by default.
    deploy: { healthcheckPath: "/health" },
    replicas: { [REGION]: 1 },
    env: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      APPLE_AUDIENCE: "com.sampocs.archie",
      ARCHIE_ENV: "prod",
      OWNER_EMAILS: preserve(),
      ANTHROPIC_API_KEY: preserve(),
      GROQ_API_KEY: preserve(),
      OPENAI_API_KEY: preserve(),
      SUPADATA_API_KEY: preserve(),
      INGEST_SECRET: preserve(),
      INGEST_EMAIL_DOMAIN: preserve(),
      INGEST_ALIASES: preserve(),
      // Pinned because the generated domain targets port 8000.
      PORT: "8000",
    },
  });

  return project("archie", {
    resources: [Postgres, archie, postgresVolume],
  });
});
