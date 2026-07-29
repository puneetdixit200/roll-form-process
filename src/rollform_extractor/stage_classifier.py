from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from rollform_extractor.models import ProfileRecord, RollerOccurrenceRecord, StationRecord, StationTransitionRecord


TOOLING_STAGE_TYPES = {"FORMING_STATION", "CALIBRATION_STATION"}


def assign_stage_types(
    stations: Iterable[StationRecord],
    profiles: Iterable[ProfileRecord],
    rollers: Iterable[RollerOccurrenceRecord] = (),
) -> tuple[StationRecord, ...]:
    station_records = tuple(stations)
    profile_by_station = {profile.station_id: profile for profile in profiles}
    composite_by_station = {
        profile.station_id
        for profile in profiles
        if profile.method == "composite_flower_detector" or profile.features.get("evidence", {}).get("composite_flower")
    }
    roller_count_by_station: dict[str, int] = {}
    for roller in rollers:
        roller_count_by_station[roller.station_id] = roller_count_by_station.get(roller.station_id, 0) + 1

    max_by_sequence: dict[int, int] = {}
    for station in station_records:
        sequence_id = _sequence_id(station)
        if station.sequence_index is not None:
            max_by_sequence[sequence_id] = max(max_by_sequence.get(sequence_id, 0), station.sequence_index)

    typed = []
    for station in station_records:
        existing = str(station.evidence.get("stage_type") or "").upper()
        confirmed = bool(station.evidence.get("confirmed")) or station.method == "manual_override"
        region_type = existing if confirmed and existing else _infer_stage_type(station, profile_by_station, roller_count_by_station, max_by_sequence, composite_by_station)
        machine_station = confirmed and region_type in TOOLING_STAGE_TYPES
        evidence = {
            **dict(station.evidence),
            "region_type": region_type,
            "stage_type": region_type,
            "confirmation_status": "confirmed" if confirmed else "candidate",
            "machine_tooling_station": machine_station,
        }
        typed.append(replace(station, evidence=evidence))
    return tuple(typed)


def confirmed_transitions(
    stations: Iterable[StationRecord],
    profiles: Iterable[ProfileRecord],
    config_hash: str,
    units_confirmed: bool,
) -> tuple[StationTransitionRecord, ...]:
    if not units_confirmed:
        return ()
    profile_records = tuple(profile for profile in profiles if profile.confidence >= 0.7)
    profile_by_station: dict[str, list[ProfileRecord]] = {}
    for profile in profile_records:
        profile_by_station.setdefault(profile.station_id, []).append(profile)
    by_sequence: dict[int, list[StationRecord]] = {}
    for station in stations:
        region_type = station.evidence.get("region_type", station.evidence.get("stage_type"))
        if station.evidence.get("confirmed") and region_type in {"FLOWER_PROFILE", "COMPOSITE_FLOWER", "FINAL_PROFILE", *TOOLING_STAGE_TYPES}:
            by_sequence.setdefault(_sequence_id(station), []).append(station)
    transitions: list[StationTransitionRecord] = []
    for sequence_id, rows in by_sequence.items():
        ordered_profiles: list[tuple[StationRecord, ProfileRecord]] = []
        for station in sorted(rows, key=lambda item: item.sequence_index or 0):
            station_profiles = sorted(profile_by_station.get(station.station_id, ()), key=lambda profile: int(profile.features.get("composite_pass_index", 0)))
            ordered_profiles.extend((station, profile) for profile in station_profiles)
        for (left_station, left_profile), (right_station, right_profile) in zip(ordered_profiles, ordered_profiles[1:]):
            transitions.append(_transition(sequence_id, left_station, right_station, left_profile, right_profile, config_hash))
    return tuple(transitions)


def _transition(
    sequence_id: int,
    left: StationRecord,
    right: StationRecord,
    left_profile: ProfileRecord,
    right_profile: ProfileRecord,
    config_hash: str,
) -> StationTransitionRecord:
    left_box = left_profile.features.get("bbox")
    right_box = right_profile.features.get("bbox")
    measurements = {
        "width_change_mm": _span(right_box, "x") - _span(left_box, "x"),
        "height_change_mm": _span(right_box, "y") - _span(left_box, "y"),
        "developed_length_change_mm": float(right_profile.features.get("exact_length", 0.0)) - float(left_profile.features.get("exact_length", 0.0)),
        "bend_angle_changes": _bend_angle_changes(left_profile, right_profile),
        "contour_distance": _contour_distance(left_profile, right_profile),
        "confirmation_status": "confirmed",
    }
    return StationTransitionRecord(
        from_station_id=left.station_id,
        to_station_id=right.station_id,
        sequence_id=sequence_id,
        measurements=measurements,
        source_handles=tuple(dict.fromkeys(left_profile.source_handles + right_profile.source_handles)),
        method="confirmed_manual_review",
        configuration_hash=config_hash,
        confidence=min(left.confidence, right.confidence, left_profile.confidence, right_profile.confidence),
    )


def _span(box, axis: str) -> float:
    if box is None:
        return 0.0
    if axis == "x":
        return float(box.max_x - box.min_x)
    return float(box.max_y - box.min_y)


def _bend_angle_changes(left: ProfileRecord, right: ProfileRecord) -> list[float]:
    left_angles = [float(value) for value in left.features.get("bend_angles", ())]
    right_angles = [float(value) for value in right.features.get("bend_angles", ())]
    return [round(r - l, 6) for l, r in zip(left_angles, right_angles)]


def _contour_distance(left: ProfileRecord, right: ProfileRecord) -> float | None:
    left_points = left.features.get("sampled_points", ())
    right_points = right.features.get("sampled_points", ())
    if not left_points or not right_points:
        return None
    count = min(len(left_points), len(right_points))
    if count == 0:
        return None
    total = 0.0
    for left_point, right_point in zip(tuple(left_points)[:count], tuple(right_points)[:count]):
        total += ((float(left_point[0]) - float(right_point[0])) ** 2 + (float(left_point[1]) - float(right_point[1])) ** 2) ** 0.5
    return total / count


def _infer_stage_type(
    station: StationRecord,
    profile_by_station: dict[str, ProfileRecord],
    roller_count_by_station: dict[str, int],
    max_by_sequence: dict[int, int],
    composite_by_station: set[str],
) -> str:
    if station.station_id in composite_by_station:
        return "COMPOSITE_FLOWER"
    has_profile = station.station_id in profile_by_station
    has_tooling = roller_count_by_station.get(station.station_id, 0) > 0
    if not has_profile and not has_tooling:
        return "REFERENCE_GEOMETRY"
    if has_tooling and not has_profile:
        return "ROLLER_DETAIL"
    if station.sequence_index == 1:
        return "FLAT_STRIP"
    if station.sequence_index == max_by_sequence.get(_sequence_id(station)):
        return "FINAL_PROFILE"
    if has_profile:
        return "FLOWER_PROFILE"
    return "UNCLASSIFIED"


def _sequence_id(station: StationRecord) -> int:
    try:
        return int(station.evidence.get("sequence_id") or 1)
    except (TypeError, ValueError):
        return 1
