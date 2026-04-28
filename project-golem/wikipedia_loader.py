#!/usr/bin/env python3
"""
Wikipedia Loader for Project Golem
Fetches Wikipedia articles, generates embeddings, and inserts into pgvector
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
import requests
import wikipediaapi
import yaml
from pgvector.psycopg2 import register_vector


# Wikipedia article topics organized by category (200+ articles)
ARTICLE_CATEGORIES = {
    "AI & Machine Learning": [
        "Artificial intelligence", "Machine learning", "Deep learning",
        "Neural network", "Natural language processing", "Computer vision",
        "Reinforcement learning", "Transformer (machine learning)",
        "Generative adversarial network", "Convolutional neural network",
        "Recurrent neural network", "Attention mechanism",
        "Large language model", "GPT-3", "BERT (language model)",
        "Artificial general intelligence", "Expert system", "Fuzzy logic",
        "Genetic algorithm", "Swarm intelligence", "Backpropagation"
    ],

    "Robotics & Automation": [
        "Robotics", "Industrial robot", "Autonomous robot",
        "Humanoid robot", "Mobile robot", "Robot kinematics",
        "SLAM (Robotics)", "Path planning", "Robot learning",
        "Swarm robotics", "Soft robotics", "Nanorobotics",
        "Robot locomotion", "Actuator", "Sensor", "Servomechanism"
    ],

    "Quantum & Physics": [
        "Quantum computing", "Quantum mechanics", "Qubit",
        "Quantum entanglement", "Quantum superposition",
        "Quantum algorithm", "Shor's algorithm", "Grover's algorithm",
        "Quantum error correction", "Quantum supremacy",
        "Quantum cryptography", "General relativity", "Special relativity",
        "String theory", "Particle physics", "Higgs boson"
    ],

    "Neuroscience & Cognition": [
        "Neuroscience", "Brain", "Neuron", "Synapse",
        "Neural circuit", "Neuroplasticity", "Cognitive neuroscience",
        "Computational neuroscience", "Neurotransmitter",
        "Action potential", "Brain-computer interface",
        "Consciousness", "Memory", "Cerebral cortex", "Hippocampus"
    ],

    "Space & Astronomy": [
        "Astronomy", "Astrophysics", "Black hole", "Neutron star",
        "Galaxy", "Solar System", "Exoplanet", "Cosmology",
        "Dark matter", "Dark energy", "Big Bang", "Gravitational wave",
        "James Webb Space Telescope", "Mars", "SpaceX",
        "International Space Station", "Asteroid", "Comet"
    ],

    "Cryptography & Security": [
        "Cryptography", "Public-key cryptography", "RSA (cryptosystem)",
        "Elliptic-curve cryptography", "Blockchain", "Bitcoin",
        "Ethereum", "Smart contract", "Zero-knowledge proof",
        "Homomorphic encryption", "Digital signature", "Hash function",
        "Advanced Encryption Standard", "Diffie-Hellman key exchange"
    ],

    "Renaissance & Art": [
        "Renaissance", "Leonardo da Vinci", "Michelangelo",
        "Raphael", "Florence", "Medici family",
        "Italian Renaissance", "Northern Renaissance",
        "Renaissance humanism", "Renaissance art", "Baroque",
        "Impressionism", "Cubism", "Surrealism"
    ],

    "Biology & Genetics": [
        "Biology", "DNA", "RNA", "Protein", "Gene",
        "Evolution", "Natural selection", "CRISPR",
        "Genetics", "Cell biology", "Molecular biology",
        "Synthetic biology", "Biotechnology", "Immunology",
        "Photosynthesis", "Mitosis", "Meiosis"
    ],

    "Computer Science": [
        "Computer science", "Algorithm", "Data structure",
        "Computational complexity theory", "P versus NP problem",
        "Distributed computing", "Cloud computing",
        "Compiler", "Operating system", "Database",
        "Computer network", "Internet protocol suite",
        "Software engineering", "Version control"
    ],

    "Mathematics": [
        "Mathematics", "Calculus", "Linear algebra",
        "Differential equation", "Topology", "Group theory",
        "Number theory", "Graph theory", "Game theory",
        "Probability theory", "Statistics", "Chaos theory",
        "Set theory", "Category theory", "Complex analysis"
    ],

    "Philosophy & Logic": [
        "Philosophy", "Epistemology", "Metaphysics", "Ethics",
        "Logic", "Philosophy of mind", "Existentialism",
        "Phenomenology", "Utilitarianism", "Stoicism",
        "Pragmatism", "Rationalism", "Empiricism"
    ],

    "History": [
        "World War II", "Roman Empire", "Ancient Egypt",
        "Industrial Revolution", "French Revolution",
        "Cold War", "Ancient Greece", "Byzantine Empire",
        "Ottoman Empire", "Mongol Empire", "Renaissance",
        "Age of Enlightenment", "American Revolution"
    ],

    "Economics & Finance": [
        "Economics", "Macroeconomics", "Microeconomics",
        "Game theory", "Supply and demand", "Keynesian economics",
        "Austrian School", "Behavioral economics",
        "International trade", "Cryptocurrency", "Stock market",
        "Monetary policy", "Fiscal policy"
    ],

    "Chemistry": [
        "Chemistry", "Organic chemistry", "Inorganic chemistry",
        "Physical chemistry", "Biochemistry", "Chemical bond",
        "Periodic table", "Atom", "Molecule", "Chemical reaction",
        "Thermochemistry", "Electrochemistry"
    ]
}


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml"""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        print("❌ Error: config.yaml not found")
        sys.exit(1)

    with open(config_path) as f:
        return yaml.safe_load(f)


def connect_to_database(db_config: dict[str, Any]) -> psycopg2.extensions.connection:
    """Connect to pgvector database"""
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


def discover_table_name(conn: psycopg2.extensions.connection) -> str:
    """Discover LLaMA Stack vector store table name"""
    cursor = conn.cursor()
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
        sys.exit(1)

    return result[0]


def get_embedding(text: str, embedding_config: dict[str, Any]) -> list[float] | None:
    """Get embedding from Qwen3-Embedding-8B"""
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
        return data['data'][0]['embedding']
    except Exception as e:
        print(f"  ❌ Embedding failed: {e}")
        return None


def insert_to_pgvector(
    conn: psycopg2.extensions.connection,
    table_name: str,
    article_id: str,
    content: str,
    category: str,
    embedding: list[float],
) -> bool:
    """Insert article into pgvector table"""
    cursor = conn.cursor()

    try:
        # LLaMA Stack schema: id, document (jsonb), embedding, content_text, tokenized_content
        # We'll populate the fields that make sense
        document_json = {
            "id": article_id,
            "category": category,
            "source": "wikipedia"
        }

        # Convert embedding list to pgvector format
        embedding_str = f"[{','.join(map(str, embedding))}]"

        cursor.execute(f"""
            INSERT INTO {table_name} (id, document, embedding, content_text)
            VALUES (%s, %s, %s::vector, %s)
        """, (article_id, json.dumps(document_json), embedding_str, content))

        conn.commit()
        cursor.close()
        return True

    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cursor.close()
        print(f"  ⚠️  Already exists")
        return False
    except Exception as e:
        conn.rollback()
        cursor.close()
        print(f"  ❌ Insert failed: {e}")
        return False


def main() -> None:
    print("🧠 Project Golem - Wikipedia Loader")
    print("=" * 70)

    # Count total articles
    total_articles = sum(len(articles) for articles in ARTICLE_CATEGORIES.values())
    print(f"Categories: {len(ARTICLE_CATEGORIES)}")
    print(f"Total articles to ingest: {total_articles}")
    print()

    # Load config and connect
    config = load_config()
    print("🔗 Connecting to database...")
    conn = connect_to_database(config['database'])
    table_name = discover_table_name(conn)
    print(f"✓ Connected to table: {table_name}")
    print()

    # Initialize Wikipedia
    wiki = wikipediaapi.Wikipedia(
        user_agent='ProjectGolem/1.0 (educational visualization project)',
        language='en'
    )

    # Statistics
    ingested = 0
    skipped = 0
    failed = 0
    start_time = time.time()

    # Process each category
    for category, articles in ARTICLE_CATEGORIES.items():
        print(f"\n📚 {category} ({len(articles)} articles)")
        print("-" * 70)

        for i, title in enumerate(articles, 1):
            print(f"[{i}/{len(articles)}] {title[:45]:45}...", end=" ", flush=True)

            # Fetch article
            page = wiki.page(title)
            if not page.exists():
                print("⊘ not found")
                skipped += 1
                continue

            content = page.summary
            if len(content) < 100:
                print("⊘ too short")
                skipped += 1
                continue

            print(f"({len(content):4} chars)...", end=" ", flush=True)

            # Get embedding
            embedding = get_embedding(content, config['embedding'])
            if not embedding:
                failed += 1
                continue

            print("emb...", end=" ", flush=True)

            # Insert to database
            article_id = title.lower().replace(' ', '_').replace('(', '').replace(')', '').replace(',', '')
            success = insert_to_pgvector(conn, table_name, article_id, content, category, embedding)

            if success:
                ingested += 1
                print("✓")
            else:
                if "already exists" not in str(success):
                    failed += 1

            # Rate limiting
            time.sleep(0.3)

    conn.close()

    # Summary
    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print("📊 Ingestion Summary")
    print("=" * 70)
    print(f"✓ Ingested:  {ingested:3}")
    print(f"⊘ Skipped:   {skipped:3}")
    print(f"✗ Failed:    {failed:3}")
    print(f"⏱  Duration:  {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"📈 Rate:      {ingested/elapsed:.1f} articles/sec")
    print()
    print(f"💡 Run 'python ingest.py' to regenerate the visualization")
    print()


if __name__ == '__main__':
    main()
