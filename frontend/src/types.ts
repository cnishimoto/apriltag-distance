/** JSON contract exposed by the local Python server. Distances are meters. */
export interface AppConfig {
  width: number;
  height: number;
  calibrated: boolean;
  calibration: { K: number[][] | null; dist: number[] | null };
  calibration_width: number | null;
  calibration_height: number | null;
  tag: {
    dictionary: string;
    tag_size_m: number;
    corner_refinement: string;
    smoothing_alpha: number;
  };
}
export type Point = [number, number];
export interface TagMeasurement {
  id: number;
  corners: [Point, Point, Point, Point];
  distance_m: number | null;
  raw_distance_m: number | null;
  depth_m: number | null;
  reprojection_error_px: number | null;
  note: string | null;
}
export interface FrameResult {
  tags: TagMeasurement[];
  width: number;
  height: number;
  warning: string | null;
  processing_ms: number;
}
export type DetectorResponse = FrameResult | { error: string };
