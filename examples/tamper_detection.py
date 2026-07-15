"""Demonstrates tamper detection with hash chain verification."""

import os
import sqlite3
import tempfile

from provena import ContextTrail

# Create a trail with HMAC signing (compliance mode)
db_path = tempfile.mktemp(suffix=".db")
trail = ContextTrail(storage_path=db_path, signing_key="my-secret-key")

# Log some context entries
for i in range(5):
    trail.log(f"Document chunk {i}: important business data.", source="retriever")

# Verify - should be intact
verdict = trail.verify_chain()
print(f"Before tampering: {verdict.details}")
trail.close()

# --- Simulate an attacker modifying a record ---
conn = sqlite3.connect(db_path)
conn.execute("UPDATE trail SET content_hash = 'ATTACKER_MODIFIED' WHERE id = 3")
conn.commit()
conn.close()
print("Attacker modified record 3...")

# Re-open and verify - should detect the tamper
trail = ContextTrail(storage_path=db_path, signing_key="my-secret-key")
verdict = trail.verify_chain()
print(f"After tampering:  {verdict.details}")
assert not verdict.intact
assert verdict.broken_at == 3
trail.close()

# Cleanup
os.unlink(db_path)
print("\nTamper detection working correctly!")
