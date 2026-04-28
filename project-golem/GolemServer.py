#!/usr/bin/env python3
"""
Project Golem - Visualization Server
Flask server that serves the Three.js frontend and handles query requests
via Qwen3-Embedding-8B and pgvector similarity search.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import requests
import yaml
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from pgvector.psycopg2 import register_vector

app = Flask(__name__,
            template_folder='app/templates',
            static_folder='app/static')
CORS(app)

# Global state
config = None
cortex = None
db_conn = None
table_name = None


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml"""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        print("❌ Error: config.yaml not found")
        print("   Run: cp config.example.yaml config.yaml")
        sys.exit(1)

    with open(config_path) as f:
        return yaml.safe_load(f)


def load_cortex() -> dict[str, Any]:
    """Load the cortex visualization data"""
    # Check /data first (for containerized deployments), then local directory
    data_path = Path("/data/golem_cortex.json")
    local_path = Path(__file__).parent / "golem_cortex.json"

    cortex_path = data_path if data_path.exists() else local_path

    if not cortex_path.exists():
        print("❌ Error: golem_cortex.json not found")
        print(f"   Checked: {data_path} and {local_path}")
        print("   Run 'python ingest.py' first to generate the cortex")
        sys.exit(1)

    print(f"📂 Loading cortex from: {cortex_path}")
    with open(cortex_path) as f:
        return json.load(f)


def connect_to_database() -> psycopg2.extensions.connection:
    """Establish persistent database connection"""
    db_config = config['database']
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
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)


def discover_table_name() -> str:
    """Discover LLaMA Stack vector store table name (pattern: vs_vs_<uuid>)"""
    cursor = db_conn.cursor()

    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_name LIKE 'vs_vs_%'
        ORDER BY table_name
        LIMIT 1
    """)

    result = cursor.fetchone()
    cursor.close()

    if not result:
        print("❌ Error: No LLaMA Stack vector store table found")
        print("   Expected table matching pattern 'vs_vs_*'")
        sys.exit(1)

    return result[0]


def get_embedding(text: str) -> list[float]:
    """Get embedding from Qwen3-Embedding-8B"""
    embedding_config = config['embedding']

    try:
        response = requests.post(
            embedding_config['url'],
            json={
                "input": text,
                "model": embedding_config['model']
            },
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        embedding = data['data'][0]['embedding']

        # Validate dimensions
        if len(embedding) != embedding_config['dimensions']:
            print(f"⚠️  Warning: Embedding dimension mismatch: "
                  f"expected {embedding_config['dimensions']}, got {len(embedding)}")

        return embedding

    except requests.exceptions.RequestException as e:
        print(f"❌ Embedding request failed: {e}")
        raise


def search_vectors(query_embedding: list[float], top_k: int = 10) -> list[dict[str, Any]]:
    """Search pgvector for similar vectors"""
    cursor = db_conn.cursor()

    # pgvector similarity search
    # <-> is L2 distance (lower is more similar)
    # <#> is inner product (higher is more similar for normalized vectors)
    # <=> is cosine distance (lower is more similar)

    # LLaMA Stack schema: id, document (jsonb), embedding, content_text, tokenized_content
    # Cast query_embedding to pgvector's vector type
    query_vector = f"[{','.join(map(str, query_embedding))}]"
    cursor.execute(f"""
        SELECT id, content_text, embedding <=> %s::vector AS distance
        FROM {table_name}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (query_vector, query_vector, top_k))

    results = cursor.fetchall()
    cursor.close()

    # Format results
    return [
        {
            'id': str(row[0]),
            'content': row[1],
            'distance': float(row[2]),
            'similarity': 1.0 - float(row[2])  # Convert distance to similarity
        }
        for row in results
    ]


# Routes

@app.route('/')
def index() -> str:
    """Serve the main visualization page"""
    return render_template('index.html')


@app.route('/cortex')
def get_cortex() -> Response:
    """Return the cortex data for visualization"""
    return jsonify(cortex)


@app.route('/query')
def query() -> tuple[Response, int] | Response:
    """
    Handle search queries
    Query params: ?q=<query text>&k=<top_k>
    """
    query_text = request.args.get('q', '')
    top_k = int(request.args.get('k', 10))

    if not query_text:
        return jsonify({'error': 'Missing query parameter q'}), 400

    try:
        # Get embedding for query
        query_embedding = get_embedding(query_text)

        # Search similar vectors
        results = search_vectors(query_embedding, top_k)

        return jsonify({
            'query': query_text,
            'results': results
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stats')
def stats() -> Response:
    """Return cortex statistics"""
    return jsonify(cortex.get('stats', {}))


@app.route('/health')
def health() -> Response:
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'cortex_loaded': cortex is not None,
        'db_connected': db_conn is not None and not db_conn.closed,
        'embedding_url': config['embedding']['url']
    })


# Static files
@app.route('/static/<path:path>')
def send_static(path: str) -> Response:
    return send_from_directory('app/static', path)


def main() -> None:
    """Start the server"""
    global config, cortex, db_conn, table_name

    print("🧠 Starting Golem Neural Memory Visualizer...")
    print("=" * 50)

    # Load configuration
    config = load_config()

    # Load cortex data
    cortex = load_cortex()
    print(f"✓ Loaded cortex: {cortex['stats']['total_nodes']} nodes, "
          f"{cortex['stats']['total_edges']} edges")

    # Connect to database
    db_conn = connect_to_database()
    print(f"✓ Database connected: {config['database']['database']}")

    # Discover table name
    table_name = discover_table_name()
    print(f"✓ Using table: {table_name}")

    # Verify embedding endpoint
    embedding_url = config['embedding']['url']
    print(f"✓ Embedding endpoint: {embedding_url}")

    print("=" * 50)

    # Start server
    server_config = config['server']
    print(f"🌐 Server running at http://{server_config['host']}:{server_config['port']}")
    print()
    print("Controls:")
    print("  - Left Click + Drag: Rotate")
    print("  - Right Click + Drag: Pan")
    print("  - Scroll: Zoom")
    print("  - Search Bar: Query the memory")
    print()

    try:
        app.run(
            host=server_config['host'],
            port=server_config['port'],
            debug=False
        )
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    finally:
        if db_conn and not db_conn.closed:
            db_conn.close()


if __name__ == '__main__':
    main()
