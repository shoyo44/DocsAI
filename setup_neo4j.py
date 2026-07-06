"""
One-time setup: Create the Neo4j vector index for chunk embeddings.
Cloudflare BGE-large-en-v1.5 produces 1024-dimension embeddings.
"""
import os
from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

print(f"Connecting to {URI} ...")
driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
driver.verify_connectivity()
print("Connected OK!")

with driver.session(database=DATABASE) as session:
    # Drop old index if exists (ignore error if not found)
    try:
        session.run("DROP INDEX chunk_embeddings IF EXISTS")
        print("Dropped old index (if existed).")
    except Exception as e:
        print(f"Note: {e}")

    # Create vector index — 1024 dims for BGE-large-en-v1.5
    session.run("""
        CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {
            indexConfig: {
                `vector.dimensions`: 1024,
                `vector.similarity_function`: 'cosine'
            }
        }
    """)
    print("Vector index 'chunk_embeddings' created (1024 dims, cosine).")

    # Check index status
    result = session.run("SHOW INDEXES WHERE name = 'chunk_embeddings'")
    for r in result:
        print(f"Index state: {r['state']} | Type: {r['type']} | Name: {r['name']}")

    # Count existing chunks
    count = session.run("MATCH (c:Chunk) RETURN count(c) AS n").single()["n"]
    print(f"Total chunks in DB: {count}")

driver.close()
print("Done!")
