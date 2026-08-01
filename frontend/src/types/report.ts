export type UploadResult = { project_id: string; job_id: string };

export type JobStage = {
  stage: string;
  status: string;
  started_at?: string;
  ended_at?: string;
  logs?: string[];
  warnings?: string[];
};

export type JobRecord = {
  job_id: string;
  project_id: string;
  status: string;
  stages: JobStage[];
  logs: Array<{ at: string; stage: string; message: string }>;
};

export type ProjectRecord = {
  project_id: string;
  job_id: string;
  revision: number;
  status: string;
  source: { stored_path: string; sha256: string };
  summary?: ProjectSummary;
};

export type ProjectSummary = {
  project_path: string;
  candidate_extraction: boolean;
  production_approved: boolean;
  composite_flower_count: number;
  candidate_pass_count: number;
  canonical_bend_zone_count: number;
  profile_step_change_count: number;
  bend_change_event_count: number;
  segment_change_event_count: number;
  confirmed_transition_count: number;
  units_confirmed: boolean;
  unresolved_review_items: Array<{ from: string; to: string; choices: string[] }>;
  feature_summary?: FeatureSummary;
};

export type FeatureSummary = {
  feature_set_count: number;
  feature_schema_version: number;
  scalar_vector_length: number;
  shape_vector_length: number;
  full_vector_length: number;
  passes_with_warnings: number;
  passes_with_unconfirmed_units: number;
};

export type BendZone = {
  bend_id: string;
  bend_zone_id: string;
  u: number;
  signed_bend_angle: number;
  zone_length: number;
  contributing_vertex_count: number;
};

export type FlowerPass = {
  pass_id: string;
  name: string;
  status: string;
  profile_type: string;
  inferred_order: number;
  engineer_confirmed_order: number | null;
  width: number;
  height: number;
  expected_neutral_length: number;
  generated_neutral_length: number;
  neutral_length_error_percent: number;
  physical_forming_bend_count: number;
  physical_total_bend_angle: number;
  vertex_turn_count: number;
  bend_zones: BendZone[];
  preview_path?: string;
  outline_preview_path?: string;
  neutral_line_preview_path?: string;
  downloads: Record<string, string>;
  feature_downloads?: Record<string, string | null>;
  feature_schema_version?: number;
  feature_vector_length?: number;
  fingerprints?: Record<string, string>;
  features?: {
    manufacturing?: { values?: Record<string, number | string | null> };
    quality?: { confidence?: number; flags?: string[]; units_status?: string; review_required?: boolean };
  };
};

export type StepChange = {
  from_pass_id: string;
  to_pass_id: string;
  width_delta: number;
  height_delta: number;
  developed_length_delta: number;
  maximum_material_point_displacement: number;
  classifications: string[];
  summary: string;
  review_choices?: string[];
};

export type CompositeFlower = {
  composite_flower_id: string;
  label: string;
  pass_count: number;
  status: string;
  passes: FlowerPass[];
  profile_step_changes: StepChange[];
  bend_change_events: unknown[];
  segment_change_events: unknown[];
  warnings?: unknown[];
};

export type ReportData = {
  project: {
    drawing_id: string;
    engineering_status: string;
    units: { confirmed?: boolean; detected?: string };
  confirmed_transitions: number;
  feature_summary?: FeatureSummary;
};
  sequences: Array<{ sequence_id: string; label: string; steps: unknown[] }>;
  composite_flowers: CompositeFlower[];
  warnings: Array<{ code: string; message: string; source_handles?: string[] }>;
};
