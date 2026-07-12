import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ragbooster.retriever import BM25Retriever, chunk_text, tokenize


def test_tokenize_lowercases_and_strips_punctuation():
    assert tokenize("Hello, World!") == ["hello", "world"]


def test_chunk_text_respects_overlap():
    words = " ".join(f"w{i}" for i in range(20))
    chunks = chunk_text(words, chunk_size=10, overlap=3)
    # first chunk: w0..w9 ; second chunk starts at w7 (10-3 step)
    assert chunks[0].split()[0] == "w0"
    assert chunks[1].split()[0] == "w7"


def test_chunk_text_rejects_overlap_ge_chunk_size():
    try:
        chunk_text("a b c", chunk_size=5, overlap=5)
        assert False, "should have raised"
    except ValueError:
        pass


def test_retrieval_finds_the_right_chunk():
    """
    This is the test the original repo never actually had: does the
    retriever return the chunk that contains the answer to a specific
    question, out of several distractor chunks?
    """
    r = BM25Retriever()
    r.add_chunk("The Eiffel Tower was completed in 1889 in Paris, France.")
    r.add_chunk("Mount Everest is the tallest mountain above sea level on Earth.")
    r.add_chunk("The Great Wall of China stretches over 21000 kilometers.")
    r.add_chunk("Python is a popular programming language created in 1991.")

    hits = r.search("When was the Eiffel Tower built?", top_k=1)
    assert len(hits) == 1
    top_chunk_id, _ = hits[0]
    assert "Eiffel" in r.chunks[top_chunk_id].text


def test_rare_term_outranks_common_term_chunk():
    """
    IDF sanity check: a chunk matching a rare, discriminative query word
    should outrank a chunk that only matches common words shared by
    every chunk in the corpus. Plain term-frequency counting (what the
    old repo did) cannot make this distinction.
    """
    r = BM25Retriever()
    # "the" appears in every chunk -> low IDF, shouldn't dominate scoring
    r.add_chunk("the quick brown fox jumps over the lazy dog in the park")
    r.add_chunk("the cat sat on the mat in the sun near the door")
    r.add_chunk("the wizard cast a rare arcane spell called xenomorphic frost")

    hits = r.search("xenomorphic spell", top_k=1)
    assert "xenomorphic" in r.chunks[hits[0][0]].text


def test_reloading_same_chunk_id_does_not_inflate_doc_frequency():
    r = BM25Retriever()
    cid = r.add_chunk("apple banana cherry", chunk_id="fixed-id")
    r.add_chunk("apple banana cherry", chunk_id="fixed-id")  # re-add same id
    assert r.doc_freq["apple"] == 1  # not 2 — old code had no such guard


def test_save_and_load_roundtrip(tmp_path):
    r = BM25Retriever()
    r.add_document("Guido van Rossum created Python. It first appeared in 1991.",
                    chunk_size=6, overlap=2)
    path = str(tmp_path / "index.json")
    r.save(path)

    r2 = BM25Retriever.load(path)
    assert r2.get_stats()["total_chunks"] == r.get_stats()["total_chunks"]
    hits = r2.search("Who created Python?", top_k=1)
    assert "Guido" in r2.chunks[hits[0][0]].text


def test_empty_index_search_returns_empty():
    r = BM25Retriever()
    assert r.search("anything") == []
