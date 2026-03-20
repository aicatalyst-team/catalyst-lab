# Wikipedia Ingestion Guide

This guide explains how to populate Project Golem with 200+ Wikipedia articles to create a robust visualization.

## Overview

The `wikipedia_loader.py` script will:
- Fetch **200+ Wikipedia articles** across 14 diverse categories
- Generate **4096-dimension embeddings** via Qwen3-Embedding-8B
- Insert directly into your **pgvector database**
- Track progress and provide statistics

## Categories (200+ Articles)

- **AI & Machine Learning** (21 articles)
- **Robotics & Automation** (16 articles)
- **Quantum & Physics** (16 articles)
- **Neuroscience & Cognition** (15 articles)
- **Space & Astronomy** (18 articles)
- **Cryptography & Security** (14 articles)
- **Renaissance & Art** (14 articles)
- **Biology & Genetics** (17 articles)
- **Computer Science** (14 articles)
- **Mathematics** (15 articles)
- **Philosophy & Logic** (13 articles)
- **History** (13 articles)
- **Economics & Finance** (13 articles)
- **Chemistry** (12 articles)

**Total: 211 articles**

## Prerequisites

1. Running cluster with:
   - pgvector database
   - Qwen3-Embedding-8B endpoint
   - Configured `config.yaml` with database credentials

2. Install dependencies:
```bash
pip install Wikipedia-API==0.6.0
```

## Running the Loader

### Option 1: Run on Your Local Machine

```bash
# Set database password
export DB_PASSWORD='<PGVECTOR_PASSWORD>'

# Run the loader
python wikipedia_loader.py
```

This will take approximately **15-20 minutes** (0.3s per article + embedding time).

### Option 2: Run as Kubernetes Job

Create a Job manifest to run the loader in-cluster:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: golem-wikipedia-loader
  namespace: catalystlab-shared
spec:
  template:
    spec:
      containers:
      - name: loader
        image: quay.io/aicatalyst/project-golem:latest
        command: ["python", "wikipedia_loader.py"]
        env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: golem-db-secret
              key: password
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
      volumes:
      - name: config
        configMap:
          name: golem-config
      restartPolicy: Never
```

## After Ingestion

Once Wikipedia articles are loaded, regenerate the visualization:

```bash
# Run the ingest job to create new cortex
kubectl apply -f ingest-job.yaml

# Wait for completion
kubectl wait --for=condition=complete job/golem-ingest -n catalystlab-shared --timeout=300s

# Restart the visualization server to pick up new data
kubectl rollout restart deployment/project-golem -n catalystlab-shared
```

## Expected Result

After ingestion and regeneration:
- **~211 nodes** (one per Wikipedia article)
- **~1000+ edges** (KNN connections based on semantic similarity)
- **Rich clustering** by topic categories
- **Meaningful semantic search** across diverse knowledge domains

## Customization

To add your own articles, edit `ARTICLE_CATEGORIES` in `wikipedia_loader.py`:

```python
ARTICLE_CATEGORIES = {
    "Your Category": [
        "Article Title 1",
        "Article Title 2",
        # ... more articles
    ],
}
```

## Troubleshooting

**"No LLaMA Stack vector store table found"**
- Ensure pgvector table exists (check with `\dt` in psql)
- Table name should match pattern `vs_vs_*`

**"Embedding failed"**
- Verify Qwen3-Embedding-8B endpoint is accessible
- Check URL in `config.yaml`

**"Article not found"**
- Wikipedia article title must match exactly
- Check spelling and capitalization

## Performance Notes

- **Rate limiting**: Script waits 0.3s between articles (be nice to Wikipedia)
- **Embedding time**: ~0.5-1s per article depending on Qwen3 load
- **Total duration**: Expect 15-20 minutes for 200+ articles
- **Database size**: ~200MB for 200 articles with 4096d embeddings

## Next Steps

After Wikipedia ingestion, consider:
1. Adding category-based coloring to visualization
2. Implementing category filtering in the UI
3. Adding more categories/articles for even richer clustering
