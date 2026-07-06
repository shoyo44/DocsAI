"""
Diagnostic: check chunks in Neo4j, run a raw vector search, and print scores.
"""
import os, asyncio
from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase, AsyncGraphDatabase

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

print("=" * 60)
print("DIAGNOSTIC: Neo4j chunks + vector search")
print("=" * 60)

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
driver.verify_connectivity()

with driver.session(database=DATABASE) as s:
    # 1. Count chunks per tenant
    r = s.run("MATCH (c:Chunk) RETURN c.tenant_id AS t, count(c) AS n")
    print("\n[1] Chunks per tenant:")
    for row in r: print(f"    tenant={row['t']}  chunks={row['n']}")

    # 2. Sample a chunk embedding to check dims
    r = s.run("MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN c.id AS id, c.tenant_id AS t, c.text AS text, size(c.embedding) AS dims LIMIT 3")
    rows = list(r)
    print("\n[2] Sample chunks (id, tenant, dims, text[:80]):")
    sample_embedding = None
    for row in rows:
        print(f"    id={row['id'][:8]}..  tenant={row['t']}  dims={row['dims']}  text={str(row['text'])[:80]}")

    # 3. Check if vector index exists and is ONLINE
    r = s.run("SHOW INDEXES WHERE type='VECTOR'")
    print("\n[3] Vector indexes:")
    for row in r:
        print(f"    name={row['name']}  state={row['state']}  dims={row.get('options',{})}")

    # 4. Run a raw vector search with a dummy embedding (all zeros)
    r = s.run("MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN c.embedding AS emb, c.tenant_id AS t LIMIT 1")
    first = r.single()
    if first:
        test_emb = first["emb"]
        tenant   = first["t"]
        print(f"\n[4] Running raw vector search with a real chunk embedding (tenant={tenant}):")
        r2 = s.run(
            """
            CALL db.index.vector.queryNodes('chunk_embedding_idx', 10, $embedding)
            YIELD node AS chunk, score
            RETURN chunk.id AS id, chunk.tenant_id AS t, score
            ORDER BY score DESC
            """,
            embedding=test_emb
        )
        for row in r2:
            print(f"    id={row['id'][:8]}..  tenant={row['t']}  score={row['score']:.4f}")
    else:
        print("\n[4] No chunks with embeddings found!")

driver.close()
print("\nDone.")
