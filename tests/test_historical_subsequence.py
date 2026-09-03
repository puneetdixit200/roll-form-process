from rollform_extractor.historical_subsequence import best_contiguous_subsequence


def test_best_contiguous_subsequence_preserves_source_flower_and_order():
    generated = [
        {"pass_id": "g1", "shape_vector": (0.0, 0.0, 1.0, 0.0)},
        {"pass_id": "g2", "shape_vector": (0.0, 0.0, 2.0, 0.0)},
        {"pass_id": "g3", "shape_vector": (0.0, 0.0, 3.0, 0.0)},
    ]
    flowers = [{"flower_id": "F2", "passes": [
        {"pass_id": "p1", "inferred_order": 0, "shape_vector": (9.0, 9.0, 9.0, 9.0)},
        {"pass_id": "p2", "inferred_order": 1, "shape_vector": (0.0, 0.0, 2.0, 0.0)},
        {"pass_id": "p3", "inferred_order": 2, "shape_vector": (0.0, 0.0, 3.0, 0.0)},
    ]}]
    result = best_contiguous_subsequence(generated, flowers)
    assert result["source_flower_id"] == "F2"
    assert result["source_pass_ids"] == ["p2", "p3"]
    assert result["generated_pass_ids"] == ["g2", "g3"]
    assert result["mapping"][0]["generated_pass_id"] == "g2"
