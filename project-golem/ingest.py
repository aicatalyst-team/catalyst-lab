#!/usr/bin/env python3
"""
Project Golem - Ingest Script
Fetches vectors from pgvector, applies UMAP dimensionality reduction,
and generates 3D visualization data for the neural memory cortex.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import psycopg2
import umap
import yaml
from pgvector.psycopg2 import register_vector
from sklearn.neighbors import NearestNeighbors


def load_config():
    """Load configuration from config.yaml"""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        print("❌ Error: config.yaml not found")
        print("   Run: cp config.example.yaml config.yaml")
        sys.exit(1)

    with open(config_path) as f:
        return yaml.safe_load(f)


def connect_to_database(db_config):
    """Connect to pgvector database"""
    print("🔗 Connecting to pgvector...")
    try:
        # Use environment variable if set (for Kubernetes deployments)
        password = os.environ.get('DB_PASSWORD', db_config.get('password', ''))

        conn = psycopg2.connect(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=password
        )
        register_vector(conn)
        print(f"✓ Connected to {db_config['database']}")
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)


def fetch_vectors(conn):
    """Fetch all vectors from the database"""
    print("📊 Fetching vectors from database...")

    cursor = conn.cursor()

    # Find LLaMA Stack vector store table (pattern: vs_vs_<uuid>)
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_name LIKE 'vs_vs_%'
        ORDER BY table_name
        LIMIT 1
    """)

    result = cursor.fetchone()
    if not result:
        print("❌ Error: No LLaMA Stack vector store table found")
        print("   Expected table matching pattern 'vs_vs_*'")
        print("   Ensure LLaMA Stack has ingested documents first")
        sys.exit(1)

    table_name = result[0]
    print(f"   Using table: {table_name}")

    # Fetch all vectors from LLaMA Stack table
    # Schema: id, document (jsonb), embedding, content_text, tokenized_content
    try:
        cursor.execute(f"""
            SELECT id, content_text, embedding, document
            FROM {table_name}
            ORDER BY id
        """)
    except psycopg2.errors.UndefinedColumn:
        # Fallback without document column
        cursor.execute(f"""
            SELECT id, content_text, embedding
            FROM {table_name}
            ORDER BY id
        """)

    rows = cursor.fetchall()

    if not rows:
        print("❌ Error: No vectors found in database")
        print("   Use LLaMA Stack to ingest documents first")
        sys.exit(1)

    print(f"✓ Found {len(rows)} vectors in database")

    # Parse data
    vectors = []
    metadata_list = []

    for row in rows:
        vec_id = row[0]
        content = row[1]
        embedding = np.array(row[2])  # pgvector returns as list
        metadata = row[3] if len(row) > 3 else {}

        vectors.append({
            'id': vec_id,
            'content': content,
            'embedding': embedding,
            'metadata': metadata
        })

    cursor.close()
    return vectors


def apply_umap(vectors, umap_config):
    """Apply UMAP dimensionality reduction to convert 4096d → 3d"""
    print(f"🧮 Applying UMAP ({len(vectors[0]['embedding'])}d → 3d)...")

    # Extract embeddings as numpy array
    embeddings = np.array([v['embedding'] for v in vectors])

    # Check dimensions
    n_samples, n_features = embeddings.shape
    print(f"   Input shape: {n_samples} samples × {n_features} dimensions")

    # Validate UMAP parameters
    n_neighbors = umap_config['n_neighbors']
    if n_neighbors >= n_samples:
        print(f"⚠️  Warning: n_neighbors ({n_neighbors}) >= n_samples ({n_samples})")
        n_neighbors = max(2, n_samples - 1)
        print(f"   Adjusting n_neighbors to {n_neighbors}")

    # Initialize UMAP
    reducer = umap.UMAP(
        n_components=3,
        n_neighbors=n_neighbors,
        min_dist=umap_config['min_dist'],
        metric=umap_config['metric'],
        random_state=42,  # Reproducible results
        verbose=True
    )

    # Fit and transform
    try:
        positions_3d = reducer.fit_transform(embeddings)
        print("✓ UMAP complete")
        return positions_3d
    except Exception as e:
        print(f"❌ UMAP failed: {e}")
        sys.exit(1)


def build_knn_graph(positions_3d, k):
    """Build k-nearest neighbors graph for connections"""
    print(f"🔗 Building KNN graph (k={k})...")

    n_samples = positions_3d.shape[0]

    # Edge case: not enough samples for KNN
    if n_samples < 2:
        print("   ⚠️  Only 1 node - skipping KNN graph")
        return []

    # Validate k
    if k >= n_samples:
        k = max(1, n_samples - 1)
        print(f"   Adjusting k to {k}")

    # Fit KNN
    knn = NearestNeighbors(n_neighbors=k + 1, metric='euclidean')
    knn.fit(positions_3d)

    # Get neighbors (index 0 is the point itself)
    distances, indices = knn.kneighbors(positions_3d)

    # Build edge list
    edges = []
    for i, neighbors in enumerate(indices):
        for j, neighbor_idx in enumerate(neighbors[1:], start=1):  # Skip self (index 0)
            # Add undirected edge (only once per pair)
            if i < neighbor_idx:
                edges.append({
                    'source': int(i),
                    'target': int(neighbor_idx),
                    'distance': float(distances[i][j])
                })

    print(f"✓ KNN graph built ({len(edges)} connections)")
    return edges


def assign_categories(vectors):
    """Assign categories based on metadata or clustering"""
    # Simple category assignment based on metadata
    # Customize this based on your data structure

    categories = set()
    for v in vectors:
        metadata = v.get('metadata') or {}

        # Try different metadata fields
        category = 'default'
        if isinstance(metadata, dict):
            category = (
                metadata.get('category') or
                metadata.get('source') or
                metadata.get('type') or
                'default'
            )

        v['category'] = category
        categories.add(category)

    print(f"   Found {len(categories)} categories: {sorted(categories)}")
    return vectors


def save_cortex(vectors, positions_3d, edges, output_path):
    """Save visualization data to JSON"""
    print("💾 Saving to golem_cortex.json...")

    # Assign categories
    vectors = assign_categories(vectors)

    # Build nodes list
    nodes = []
    for i, vec in enumerate(vectors):
        # Truncate content for display (full content available via hover)
        content_preview = vec['content'][:200] + "..." if len(vec['content']) > 200 else vec['content']

        nodes.append({
            'id': str(vec['id']),
            'content': content_preview,
            'full_content': vec['content'],
            'position': positions_3d[i].tolist(),
            'category': vec['category'],
            'metadata': vec.get('metadata', {})
        })

    # Build cortex structure
    cortex = {
        'nodes': nodes,
        'edges': edges,
        'stats': {
            'total_nodes': len(nodes),
            'total_edges': len(edges),
            'dimensions': len(vectors[0]['embedding']),
            'categories': list(set(n['category'] for n in nodes))
        }
    }

    # Save to file
    with open(output_path, 'w') as f:
        json.dump(cortex, f, indent=2)

    print(f"✓ Cortex saved ({len(nodes)} nodes, {len(edges)} edges)")
    return cortex


def main():
    """Main ingest pipeline"""
    print("🧠 Project Golem - Cortex Builder")
    print("=" * 50)

    # Load configuration
    config = load_config()

    # Connect to database
    conn = connect_to_database(config['database'])

    # Fetch vectors
    vectors = fetch_vectors(conn)
    conn.close()

    # Apply UMAP dimensionality reduction
    positions_3d = apply_umap(vectors, config['umap'])

    # Build KNN graph
    edges = build_knn_graph(positions_3d, config['knn']['k'])

    # Save cortex
    # Use /data for containerized deployments, otherwise current directory
    output_dir = Path("/data") if Path("/data").exists() else Path(__file__).parent
    output_path = output_dir / "golem_cortex.json"
    print(f"📂 Output directory: {output_dir} (exists: {output_dir.exists()})")
    print(f"📄 Output path: {output_path}")
    cortex = save_cortex(vectors, positions_3d, edges, output_path)

    # Verify file was created
    if output_path.exists():
        size = output_path.stat().st_size
        print(f"✅ File created successfully: {output_path} ({size} bytes)")
    else:
        print(f"❌ File not found after save: {output_path}")

    print("=" * 50)
    print("🧠 Golem cortex is ready!")
    print(f"   Nodes: {cortex['stats']['total_nodes']}")
    print(f"   Edges: {cortex['stats']['total_edges']}")
    print(f"   Categories: {', '.join(cortex['stats']['categories'])}")
    print()
    print("Next: Run 'python GolemServer.py' to start the visualization")


if __name__ == '__main__':
    main()
