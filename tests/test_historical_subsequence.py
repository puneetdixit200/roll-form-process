from rollform_extractor.historical_subsequence import best_contiguous_subsequence


def test_best_contiguous_subsequence_preserves_source_flower_and_order():
    generated = [
        {"pass_id": "g1", "order": 1, "progress": 0.0, "profile": {"points": [[0, 0], [1, 0]], "topology": "OPEN_PATH"}},
        {"pass_id": "g2", "order": 2, "progress": 0.5, "profile": {"points": [[0, 0], [2, 0]], "topology": "OPEN_PATH"}},
        {"pass_id": "g3", "order": 3, "progress": 1.0, "profile": {"points": [[0, 0], [3, 0]], "topology": "OPEN_PATH"}},
    ]
    flowers = [{"flower_id": "F2", "passes": [
        {"pass_id": "p1", "inferred_order": 0, "progress": 0.0, "profile": {"points": [[9, 9], [9, 9]], "topology": "OPEN_PATH"}},
        {"pass_id": "p2", "inferred_order": 1, "progress": 0.5, "profile": {"points": [[0, 0], [2, 0]], "topology": "OPEN_PATH"}},
        {"pass_id": "p3", "inferred_order": 2, "progress": 1.0, "profile": {"points": [[0, 0], [3, 0]], "topology": "OPEN_PATH"}},
    ]}]
    result = best_contiguous_subsequence(generated, flowers, minimum_length=2)
    best = result["best_historical_subsequence"]
    assert best["source_flower_id"] == "F2"
    assert best["source_pass_ids"] == ["p2", "p3"]
    assert best["generated_pass_ids"] == ["g2", "g3"]
    assert best["mapping"][0]["generated_pass_id"] == "g2"


def test_default_window_requires_three_for_long_sequences_and_abstains_when_weak():
    profile = {"points": [[0, 0], [1, 0]], "topology": "OPEN_PATH"}
    generated = [{"pass_id": f"g{i}", "order": i, "progress": i / 3, "profile": profile} for i in range(4)]
    flowers = [{"flower_id": "F1", "passes": [{"pass_id": f"p{i}", "inferred_order": i, "progress": i / 3, "profile": profile} for i in range(4)]}]
    result = best_contiguous_subsequence(generated, flowers)
    assert result["status"] == "SUPPORTED"
    assert result["best_historical_subsequence"]["matched_length"] == 4
    weak = best_contiguous_subsequence(generated, [{"flower_id": "F9", "passes": [{"pass_id": "p", "inferred_order": 0, "progress": 0, "profile": {"points": [[10, 10], [20, 20]], "topology": "OPEN_PATH"}}]}])
    assert weak["status"] == "INSUFFICIENT_HISTORICAL_SUBSEQUENCE_SUPPORT"
