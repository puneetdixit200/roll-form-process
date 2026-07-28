from __future__ import annotations

import pytest

from rollform_extractor.benchmark import contour_metrics, evaluate_benchmark


def test_identical_contours_have_zero_distance():
    metrics = contour_metrics([(0, 0), (1, 0)], [(0, 0), (1, 0)])

    assert metrics.hausdorff_mm == 0
    assert metrics.mean_contour_mm == 0


def test_shifted_contours_report_hausdorff_and_mean_distance():
    metrics = contour_metrics([(0, 0), (10, 0)], [(0, 0.1), (10, 0.1)])

    assert metrics.hausdorff_mm == pytest.approx(0.1)
    assert metrics.mean_contour_mm == pytest.approx(0.1)


def test_benchmark_reports_detection_geometry_and_false_automatic_claims():
    report = evaluate_benchmark(_truth(), _extraction())

    assert report.station_count_accuracy == pytest.approx(0.5)
    assert report.boundary_iou == pytest.approx((1.0 + (50 / 150)) / 2)
    assert report.profile_id_accuracy == pytest.approx(0.5)
    assert report.roller_recall == pytest.approx(1 / 2)
    assert report.roller_role_accuracy == pytest.approx(1 / 2)
    assert report.incorrect_automatic_claim_rate == pytest.approx(4 / 9)
    assert report.geometry.hausdorff_mm == pytest.approx(0.1)
    assert report.geometry.mean_contour_mm == pytest.approx(0.1)
    assert report.geometry.developed_length_error_pct == pytest.approx(0.2)
    assert report.geometry.bend_position_error_mm == pytest.approx(0.2)
    assert report.geometry.bend_angle_error_deg == pytest.approx(1.0)
    assert report.geometry.bend_radius_error_mm == pytest.approx(0.6)


def test_provisional_targets_mark_dimensional_limits():
    report = evaluate_benchmark(_truth(), _extraction())

    assert report.targets["roller_recall"].passed is False
    assert report.targets["roller_recall"].provisional is False
    assert report.targets["developed_length_error_pct"].passed is False
    assert report.targets["developed_length_error_pct"].provisional is True
    assert report.targets["bend_position_error_mm"].limit == 0.2
    assert report.targets["bend_position_error_mm"].provisional is True


def test_zero_iou_station_is_not_a_match_and_counts_as_false_automatic_claim():
    truth = {"stations": [{"station_id": "S1", "bbox": {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10}}], "profiles": [], "rollers": []}
    extraction = {
        "stations": [{"station_id": "far", "bbox": {"min_x": 50, "min_y": 0, "max_x": 60, "max_y": 10}, "automatic": True}],
        "profiles": [],
        "rollers": [],
    }

    report = evaluate_benchmark(truth, extraction)

    assert report.boundary_iou is None
    assert report.incorrect_automatic_claim_rate == 1


def test_roller_role_accuracy_uses_station_matches_not_occurrence_id_only():
    truth = {
        "stations": [{"station_id": "S1", "bbox": {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10}}],
        "profiles": [],
        "rollers": [{"occurrence_id": "R1", "station_id": "S1", "role": "upper"}],
    }
    extraction = {
        "stations": [
            {"station_id": "E1", "bbox": {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10}, "automatic": True},
            {"station_id": "E2", "bbox": {"min_x": 50, "min_y": 0, "max_x": 60, "max_y": 10}, "automatic": True},
        ],
        "profiles": [],
        "rollers": [{"occurrence_id": "R1", "station_id": "E2", "role": "upper", "automatic": True}],
    }

    report = evaluate_benchmark(truth, extraction)

    assert report.roller_role_accuracy == 0


def _truth():
    return {
        "stations": [
            {"station_id": "S1", "bbox": {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10}},
            {"station_id": "S2", "bbox": {"min_x": 20, "min_y": 0, "max_x": 30, "max_y": 10}},
        ],
        "profiles": [
            {
                "profile_id": "flower-a",
                "station_id": "S1",
                "contour": [(0, 0), (10, 0)],
                "developed_length_mm": 10.0,
                "bends": [{"position_mm": 2.0, "angle_deg": 45.0, "radius_mm": 1.0}],
            },
            {"profile_id": "flower-b", "station_id": "S2"},
        ],
        "rollers": [
            {"occurrence_id": "R1", "station_id": "S1", "role": "upper"},
            {"occurrence_id": "R2", "station_id": "S2", "role": "lower"},
        ],
    }


def _extraction():
    return {
        "stations": [
            {"station_id": "E1", "bbox": {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10}, "automatic": True},
            {"station_id": "E2", "bbox": {"min_x": 25, "min_y": 0, "max_x": 35, "max_y": 10}, "automatic": True},
            {"station_id": "E3", "bbox": {"min_x": 100, "min_y": 0, "max_x": 110, "max_y": 10}, "automatic": True},
        ],
        "profiles": [
            {
                "profile_id": "flower-a",
                "station_id": "E1",
                "contour": [(0, 0.1), (10, 0.1)],
                "developed_length_mm": 10.02,
                "automatic": True,
                "bends": [{"position_mm": 2.2, "angle_deg": 46.0, "radius_mm": 1.6}],
            },
            {"profile_id": "wrong-profile", "station_id": "E2", "automatic": True},
            {"profile_id": "extra-profile", "station_id": "E3", "automatic": True},
        ],
        "rollers": [
            {"occurrence_id": "R1", "station_id": "E1", "role": "upper", "automatic": True},
            {"occurrence_id": "R2", "station_id": "E2", "role": "upper", "automatic": True},
            {"occurrence_id": "R3", "station_id": "E3", "role": "lower", "automatic": True},
        ],
    }
