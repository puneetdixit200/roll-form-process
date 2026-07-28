from __future__ import annotations

from dataclasses import dataclass
import json
from math import hypot
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


Point = tuple[float, float]


@dataclass(frozen=True)
class ContourMetrics:
    hausdorff_mm: float
    mean_contour_mm: float


@dataclass(frozen=True)
class GeometryMetrics:
    hausdorff_mm: float | None
    mean_contour_mm: float | None
    developed_length_error_pct: float | None
    bend_position_error_mm: float | None
    bend_angle_error_deg: float | None
    bend_radius_error_mm: float | None


@dataclass(frozen=True)
class TargetStatus:
    value: float | None
    limit: float
    passed: bool | None
    provisional: bool = False
    higher_is_better: bool = True


@dataclass(frozen=True)
class BenchmarkReport:
    station_count_accuracy: float
    boundary_iou: float | None
    profile_id_accuracy: float | None
    roller_recall: float | None
    roller_role_accuracy: float | None
    incorrect_automatic_claim_rate: float | None
    geometry: GeometryMetrics
    targets: Mapping[str, TargetStatus]


def evaluate_benchmark(truth: Mapping[str, Any] | str | Path, extraction: Mapping[str, Any] | str | Path) -> BenchmarkReport:
    truth_data = _load_case(truth)
    extracted = _load_case(extraction)
    matches = _station_matches(truth_data.get("stations", ()), extracted.get("stations", ()))
    profile_id_accuracy = _profile_id_accuracy(truth_data, extracted, matches)
    roller_recall = _roller_recall(truth_data, extracted, matches)
    roller_role_accuracy = _roller_role_accuracy(truth_data, extracted, matches)
    false_claim_rate = _incorrect_automatic_claim_rate(truth_data, extracted, matches)
    geometry = _geometry_metrics(truth_data, extracted, matches)
    report = BenchmarkReport(
        station_count_accuracy=_station_count_accuracy(len(truth_data.get("stations", ())), len(extracted.get("stations", ()))),
        boundary_iou=_mean([match[2] for match in matches]),
        profile_id_accuracy=profile_id_accuracy,
        roller_recall=roller_recall,
        roller_role_accuracy=roller_role_accuracy,
        incorrect_automatic_claim_rate=false_claim_rate,
        geometry=geometry,
        targets={},
    )
    return BenchmarkReport(
        **{name: getattr(report, name) for name in report.__dataclass_fields__ if name != "targets"},
        targets=_targets(report),
    )


def contour_metrics(truth: Sequence[Sequence[float]], extraction: Sequence[Sequence[float]]) -> ContourMetrics:
    truth_points = _points(truth)
    extracted_points = _points(extraction)
    if not truth_points or not extracted_points:
        return ContourMetrics(float("inf"), float("inf"))
    truth_distances = [_distance_to_polyline(point, extracted_points) for point in truth_points]
    extracted_distances = [_distance_to_polyline(point, truth_points) for point in extracted_points]
    return ContourMetrics(
        max(max(truth_distances), max(extracted_distances)),
        sum(truth_distances + extracted_distances) / (len(truth_distances) + len(extracted_distances)),
    )


def _load_case(value: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    path = Path(value)
    if path.suffix == ".sqlite":
        return _load_sqlite(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_sqlite(path: Path) -> dict[str, Any]:
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        return {
            "stations": [_json_row(row, "bbox_json") for row in db.execute("select * from stations")],
            "profiles": [_json_row(row, "features_json") for row in db.execute("select * from profiles")],
            "rollers": [_json_row(row, "evidence_json") for row in db.execute("select * from roller_occurrences")],
        }


def _json_row(row: sqlite3.Row, json_column: str) -> dict[str, Any]:
    data = dict(row)
    data[json_column] = json.loads(data[json_column]) if isinstance(data.get(json_column), str) else data.get(json_column)
    if json_column == "bbox_json":
        data["bbox"] = data.pop("bbox_json")
    elif json_column == "features_json":
        data["features"] = data.pop("features_json")
    else:
        data["evidence"] = data.pop("evidence_json")
    return data


def _station_matches(truth_stations: Sequence[Mapping[str, Any]], extracted_stations: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, float]]:
    remaining = list(extracted_stations)
    matches = []
    for truth_station in truth_stations:
        best = max(remaining, key=lambda item: _iou(truth_station.get("bbox"), item.get("bbox")), default=None)
        best_iou = _iou(truth_station.get("bbox"), best.get("bbox")) if best else 0.0
        if best is None or best_iou <= 0:
            continue
        remaining.remove(best)
        matches.append((truth_station["station_id"], best["station_id"], best_iou))
    return matches


def _station_count_accuracy(truth_count: int, extracted_count: int) -> float:
    if truth_count == 0:
        return 1.0 if extracted_count == 0 else 0.0
    return max(0.0, 1.0 - abs(extracted_count - truth_count) / truth_count)


def _profile_id_accuracy(truth: Mapping[str, Any], extracted: Mapping[str, Any], matches: list[tuple[str, str, float]]) -> float | None:
    truth_by_station = {item.get("station_id"): item.get("profile_id") for item in truth.get("profiles", ())}
    extracted_by_station = {item.get("station_id"): item.get("profile_id") for item in extracted.get("profiles", ())}
    values = [truth_by_station.get(tid) == extracted_by_station.get(eid) for tid, eid, _ in matches if tid in truth_by_station]
    return _mean_bool(values)


def _roller_recall(truth: Mapping[str, Any], extracted: Mapping[str, Any], matches: list[tuple[str, str, float]]) -> float | None:
    confident_station_matches = {truth_id: extracted_id for truth_id, extracted_id, iou in matches if iou >= 0.5}
    extracted_pairs = {(item.get("station_id"), item.get("occurrence_id")) for item in extracted.get("rollers", ())}
    values = [
        (confident_station_matches.get(item.get("station_id")), item.get("occurrence_id")) in extracted_pairs
        for item in truth.get("rollers", ())
    ]
    return _mean_bool(values)


def _roller_role_accuracy(truth: Mapping[str, Any], extracted: Mapping[str, Any], matches: list[tuple[str, str, float]]) -> float | None:
    matched_station = {truth_id: extracted_id for truth_id, extracted_id, _ in matches}
    extracted_by_station_and_id = {
        (item.get("station_id"), item.get("occurrence_id")): item.get("role")
        for item in extracted.get("rollers", ())
    }
    values = [
        extracted_by_station_and_id.get((matched_station.get(item.get("station_id")), item.get("occurrence_id"))) == item.get("role")
        for item in truth.get("rollers", ())
        if item.get("station_id") in matched_station
    ]
    return _mean_bool(values)


def _incorrect_automatic_claim_rate(truth: Mapping[str, Any], extracted: Mapping[str, Any], matches: list[tuple[str, str, float]]) -> float | None:
    claims = 0
    incorrect = 0
    truth_station_ids = {truth_id for truth_id, _, _ in matches}
    extracted_to_truth = {extracted_id: truth_id for truth_id, extracted_id, _ in matches}
    for station in extracted.get("stations", ()):
        if _automatic(station):
            claims += 1
            incorrect += station.get("station_id") not in extracted_to_truth
    truth_profiles = {(item.get("station_id"), item.get("profile_id")) for item in truth.get("profiles", ())}
    for profile in extracted.get("profiles", ()):
        if _automatic(profile):
            claims += 1
            incorrect += (extracted_to_truth.get(profile.get("station_id")), profile.get("profile_id")) not in truth_profiles
    truth_roller_ids = {item.get("occurrence_id") for item in truth.get("rollers", ()) if item.get("station_id") in truth_station_ids}
    for roller in extracted.get("rollers", ()):
        if _automatic(roller):
            claims += 1
            incorrect += roller.get("occurrence_id") not in truth_roller_ids
    return incorrect / claims if claims else None


def _geometry_metrics(truth: Mapping[str, Any], extracted: Mapping[str, Any], matches: list[tuple[str, str, float]]) -> GeometryMetrics:
    extracted_profiles = {item.get("station_id"): item for item in extracted.get("profiles", ())}
    contours = []
    length_errors = []
    position_errors = []
    angle_errors = []
    radius_errors = []
    for truth_station_id, extracted_station_id, _ in matches:
        truth_profile = next((item for item in truth.get("profiles", ()) if item.get("station_id") == truth_station_id), None)
        extracted_profile = extracted_profiles.get(extracted_station_id)
        if not truth_profile or not extracted_profile:
            continue
        truth_contour = _feature(truth_profile, "contour")
        extracted_contour = _feature(extracted_profile, "contour")
        if truth_contour and extracted_contour:
            contours.append(contour_metrics(truth_contour, extracted_contour))
        truth_length = _feature(truth_profile, "developed_length_mm")
        extracted_length = _feature(extracted_profile, "developed_length_mm")
        if truth_length:
            length_errors.append(abs(float(extracted_length or 0) - float(truth_length)) / float(truth_length) * 100)
        for truth_bend, extracted_bend in zip(_feature(truth_profile, "bends") or (), _feature(extracted_profile, "bends") or ()):
            position_errors.append(abs(float(extracted_bend.get("position_mm", 0)) - float(truth_bend.get("position_mm", 0))))
            angle_errors.append(abs(float(extracted_bend.get("angle_deg", 0)) - float(truth_bend.get("angle_deg", 0))))
            radius_errors.append(abs(float(extracted_bend.get("radius_mm", 0)) - float(truth_bend.get("radius_mm", 0))))
    return GeometryMetrics(
        _mean([item.hausdorff_mm for item in contours]),
        _mean([item.mean_contour_mm for item in contours]),
        _mean(length_errors),
        _mean(position_errors),
        _mean(angle_errors),
        _mean(radius_errors),
    )


def _targets(report: BenchmarkReport) -> dict[str, TargetStatus]:
    return {
        "station_count_accuracy": _target(report.station_count_accuracy, 0.95),
        "boundary_iou": _target(report.boundary_iou, 0.90),
        "profile_id_accuracy": _target(report.profile_id_accuracy, 0.95),
        "roller_recall": _target(report.roller_recall, 0.95),
        "roller_role_accuracy": _target(report.roller_role_accuracy, 0.95),
        "incorrect_automatic_claim_rate": _target(report.incorrect_automatic_claim_rate, 0.05, higher_is_better=False),
        "hausdorff_mm": _target(report.geometry.hausdorff_mm, 0.20, provisional=True, higher_is_better=False),
        "mean_contour_mm": _target(report.geometry.mean_contour_mm, 0.20, provisional=True, higher_is_better=False),
        "developed_length_error_pct": _target(report.geometry.developed_length_error_pct, 0.10, provisional=True, higher_is_better=False),
        "bend_position_error_mm": _target(report.geometry.bend_position_error_mm, 0.20, provisional=True, higher_is_better=False),
        "bend_angle_error_deg": _target(report.geometry.bend_angle_error_deg, 0.50, provisional=True, higher_is_better=False),
        "bend_radius_error_mm": _target(report.geometry.bend_radius_error_mm, 0.50, provisional=True, higher_is_better=False),
    }


def _target(value: float | None, limit: float, *, provisional: bool = False, higher_is_better: bool = True) -> TargetStatus:
    if value is None:
        return TargetStatus(value, limit, None, provisional, higher_is_better)
    passed = value >= limit if higher_is_better else value <= limit
    return TargetStatus(value, limit, passed, provisional, higher_is_better)


def _iou(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> float:
    if not left or not right:
        return 0.0
    width = max(0.0, min(left["max_x"], right["max_x"]) - max(left["min_x"], right["min_x"]))
    height = max(0.0, min(left["max_y"], right["max_y"]) - max(left["min_y"], right["min_y"]))
    intersection = width * height
    area = _area(left) + _area(right) - intersection
    return intersection / area if area else 0.0


def _area(bbox: Mapping[str, Any]) -> float:
    return max(0.0, float(bbox["max_x"]) - float(bbox["min_x"])) * max(0.0, float(bbox["max_y"]) - float(bbox["min_y"]))


def _distance_to_polyline(point: Point, polyline: Sequence[Point]) -> float:
    if len(polyline) == 1:
        return hypot(point[0] - polyline[0][0], point[1] - polyline[0][1])
    return min(_distance_to_segment(point, start, end) for start, end in zip(polyline, polyline[1:]))


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    vx = end[0] - start[0]
    vy = end[1] - start[1]
    length_sq = vx * vx + vy * vy
    if length_sq == 0:
        return hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * vx + (point[1] - start[1]) * vy) / length_sq))
    return hypot(point[0] - (start[0] + t * vx), point[1] - (start[1] + t * vy))


def _points(points: Sequence[Sequence[float]]) -> tuple[Point, ...]:
    return tuple((float(point[0]), float(point[1])) for point in points)


def _feature(profile: Mapping[str, Any], key: str) -> Any:
    return profile.get(key, profile.get("features", {}).get(key))


def _automatic(item: Mapping[str, Any]) -> bool:
    return bool(item.get("automatic", item.get("method") != "manual_override"))


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _mean_bool(values: Sequence[bool]) -> float | None:
    return sum(values) / len(values) if values else None
