# Deployment Guide: GateKeep RAG (100% Free Cloud Deployment)

GateKeep RAG can be deployed to the cloud completely **free of charge ($0.00/month)** with **zero credit card or payment details required**.

---

## 1. 100% Free Cloud Deployment on Render

Render provides a Free Tier for Docker web applications that does not require any payment information.

The updated [`render.yaml`](../render.yaml) is configured strictly for **`plan: free`** with zero paid dependencies (no paid private services or persistent disks).

### Steps to Deploy for Free:

1. **Log in to Render**: Go to [dashboard.render.com](https://dashboard.render.com/).
2. **Deploy via Blueprint**:
   - In the top navigation bar, click **New +** $\rightarrow$ **Blueprint**.
   - Connect your GitHub repository: `saturn-16/GateKeep-RAG`.
   - Branch: `main`.
3. **Review & Confirm ($0.00/mo)**:
   - Render will display the service `gatekeep-rag` with **Plan: Free ($0/mo)**.
   - It will **not ask for any credit card or payment**.
   - Click **Apply**.
4. **Access Your Live App**:
   - In about 2 minutes, your deployment will be live at `https://gatekeep-rag.onrender.com`.
   - Visiting the root URL immediately loads the interactive React UI with all demo personas (`alice`, `bob`, `dave`, etc.).
   - OpenAPI documentation is accessible at `/docs`.

---

## 2. Optional: Connect Free Cloud Databases (PostgreSQL + Qdrant)

If you want persistent PostgreSQL and Qdrant in the cloud without paying anything:

1. **Free Serverless PostgreSQL (Neon.tech)**:
   - Go to [neon.tech](https://neon.tech) and sign up with GitHub (free forever, 0.5 GB, no credit card required).
   - Create a project `gatekeep` and copy your Postgres connection string.
2. **Free Managed Qdrant Cluster (Qdrant Cloud)**:
   - Go to [cloud.qdrant.io](https://cloud.qdrant.io) and sign up with GitHub (free forever 1 GB cluster, no credit card required).
   - Create a free cluster and copy your cluster URL and API key.
3. **Add to Render Environment Variables**:
   In your Render dashboard for `gatekeep-rag`, go to **Environment** and set:
   - `PERSISTENCE_BACKEND`: `postgres`
   - `VECTOR_BACKEND`: `qdrant`
   - `DATABASE_URL`: `your-neon-postgres-connection-string`
   - `MIGRATION_DATABASE_URL`: `your-neon-postgres-connection-string`
   - `QDRANT_URL`: `your-qdrant-cluster-url`
   - `RUN_REAL_STACK`: `1`

---

## 3. Alternative: Run Locally with Free Public HTTPS Tunnel

If you want to run the full Docker Compose stack (Postgres 16 + Qdrant container) on your machine and share a public URL for free:

```bash
# 1. Start full local stack
docker compose up -d

# 2. Expose a public HTTPS URL using LocalTunnel (no signup, 100% free)
npx localtunnel --port 8000
```
This gives you an instant `https://*.loca.lt` link connected to your local backend.
