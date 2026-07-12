"""
benchmark.py — reproducible comparison: old engine vs new engine.

Run: python3 benchmark/benchmark.py

Measures three things, each against a concrete, checkable baseline:
  1. Memory:   tracemalloc, old GravitationalMemory vs new BM25Retriever
  2. Speed:    wall-clock indexing time, same two engines
  3. Quality:  retrieval precision@1 and precision@3 on a small labeled
               Q/A set with a known correct chunk per question — the
               original repo never measured this at all.

No cherry-picking: the labeled set is printed in full below so anyone
can inspect or extend it.
"""

import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "llm-rag-booster-allpath"))

from ragbooster.retriever import BM25Retriever  # noqa: E402

try:
    from booster import GravitationalMemory  # noqa: E402
    OLD_AVAILABLE = True
except Exception as e:
    OLD_AVAILABLE = False
    OLD_IMPORT_ERROR = e


# --------------------------------------------------------------- corpus

FACTS = [
    "The Eiffel Tower was designed by Gustave Eiffel and completed in 1889 for the World's Fair in Paris.",
    "Mount Everest, at 8849 meters, is the tallest mountain above sea level and sits on the border of Nepal and Tibet.",
    "The Great Wall of China stretches over 21000 kilometers and was built over many dynasties starting in the 7th century BC.",
    "Python was created by Guido van Rossum and first released in 1991, emphasizing readable, indented code.",
    "Rust was created by Graydon Hoare at Mozilla and first released in 2010, focused on memory safety without a garbage collector.",
    "The Amazon rainforest produces about 20 percent of the world's oxygen and spans nine South American countries.",
    "The human heart beats about 100000 times per day, pumping roughly 7500 liters of blood.",
    "Photosynthesis converts carbon dioxide and water into glucose and oxygen using energy from sunlight.",
    "The Great Barrier Reef is the largest coral reef system in the world, located off the coast of Queensland, Australia.",
    "Shakespeare wrote approximately 39 plays and 154 sonnets during his lifetime in England.",
    "The speed of light in a vacuum is approximately 299792 kilometers per second.",
    "Docker was created by Solomon Hykes and released in 2013, popularizing OS-level containerization.",
    "The Sahara desert covers most of North Africa and is roughly the size of the United States.",
    "DNA was first described as a double helix by James Watson and Francis Crick in 1953.",
    "The Colosseum in Rome could hold between 50000 and 80000 spectators for gladiatorial contests.",
]

# (question, must-appear substring that proves the RIGHT chunk was retrieved)
QUESTIONS = [
    ("Who designed the Eiffel Tower?", "Eiffel"),
    ("Who created the Rust programming language?", "Graydon Hoare"),
    ("What percentage of world oxygen does the Amazon produce?", "20 percent"),
    ("How many times does the human heart beat per day?", "100000 times"),
    ("Who discovered the structure of DNA?", "Watson and Francis Crick"),
    ("How many spectators could the Colosseum hold?", "50000 and 80000"),
    ("Who created Docker?", "Solomon Hykes"),
    ("What is the speed of light?", "299792 kilometers"),
    ("Where is the Great Barrier Reef located?", "Queensland, Australia"),
    ("How many plays did Shakespeare write?", "39 plays"),
]

DOCUMENT = " ".join(FACTS)


# ------------------------------------------------------------ quality

def eval_new_engine():
    hits_at_1, hits_at_3 = 0, 0
    r = BM25Retriever()
    r.add_document(DOCUMENT, chunk_size=18, overlap=6)
    for q, needle in QUESTIONS:
        results = r.search(q, top_k=3)
        texts = [r.chunks[cid].text for cid, _ in results]
        if texts and needle in texts[0]:
            hits_at_1 += 1
        if any(needle in t for t in texts):
            hits_at_3 += 1
    n = len(QUESTIONS)
    return hits_at_1 / n, hits_at_3 / n


def eval_old_engine():
    """Old engine only exposes retrieve_relevant_context() as a single
    concatenated string, not ranked chunk boundaries, so precision@1 in
    the same sense isn't directly comparable — instead we check whether
    the needle fact appears at all in the returned context at top_k=3
    chunk-equivalents, which is the most charitable comparison."""
    hits_at_3 = 0
    mem = GravitationalMemory(compression_level=15)
    mem.store_document(DOCUMENT, chunk_size=18)
    for q, needle in QUESTIONS:
        ctx = mem.retrieve_relevant_context(q, top_k=3)
        if needle in ctx:
            hits_at_3 += 1
    n = len(QUESTIONS)
    return hits_at_3 / n


# ------------------------------------------------------- memory & speed

def measure_new_engine(text):
    tracemalloc.start()
    t0 = time.time()
    r = BM25Retriever()
    r.add_document(text, chunk_size=200, overlap=50)
    elapsed = time.time() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, current, peak


def measure_old_engine(text):
    tracemalloc.start()
    t0 = time.time()
    mem = GravitationalMemory(compression_level=15)
    stats = mem.store_document(text, chunk_size=200)
    elapsed = time.time() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, current, peak, stats


def main():
    print("=" * 72)
    print("PART 1 — Retrieval quality (precision on a 10-question labeled set)")
    print("=" * 72)
    p1, p3 = eval_new_engine()
    print(f"New engine (BM25):        precision@1 = {p1:.0%}   precision@3 = {p3:.0%}")
    if OLD_AVAILABLE:
        old_p3 = eval_old_engine()
        print(f"Old engine (keyword-sum): precision@3 = {old_p3:.0%}  (no ranked precision@1 available)")
    else:
        print(f"Old engine unavailable: {OLD_IMPORT_ERROR}")

    print()
    print("=" * 72)
    print("PART 2 — Memory & speed on a larger synthetic document")
    print("=" * 72)
    big_text = (DOCUMENT + " ") * 60  # ~1500 words / ~10k chars
    print(f"document size: {len(big_text)} chars, {len(big_text.split())} words")

    n_elapsed, n_current, n_peak = measure_new_engine(big_text)
    print(f"New engine (BM25):        {n_elapsed*1000:.2f} ms   traced memory: {n_current:,} bytes (peak {n_peak:,})")

    if OLD_AVAILABLE:
        o_elapsed, o_current, o_peak, o_stats = measure_old_engine(big_text)
        print(f"Old engine (gravitational): {o_elapsed*1000:.2f} ms   traced memory: {o_current:,} bytes (peak {o_peak:,})")
        print(f"  old engine self-reported compression_ratio: {o_stats['compression_ratio']:.2f}x")
        print(f"  old engine self-reported integrity: {o_stats['integrity']}")
        print()
        print(f"  => new engine is {o_elapsed/n_elapsed:.1f}x faster and uses {o_current/n_current:.1f}x less traced memory")
    print()
    print("Raw numbers only — no rounding applied to ratios beyond display precision.")


if __name__ == "__main__":
    main()
