/** UUID v4 also works on local HTTP previews where randomUUID is unavailable. */
export function newRecordId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
/** Raw distance dispersion within one fixed-reference trial (sample SD, n - 1). */
export function groundTruthValue(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error('Ground-truth distance must be a positive number in meters, or left blank.');
  return number;
}
export class TrialStatistics {
  private n = 0;
  private mean = 0;
  private m2 = 0;
  private min = Infinity;
  private max = -Infinity;
  private absoluteError = 0;
  private lastFrame = '';
  constructor(readonly groundTruth: number | null) {}
  add(value: number | null, frameId: string): void {
    if (value === null || !Number.isFinite(value) || value < 0 || frameId === this.lastFrame) return;
    this.lastFrame = frameId;
    this.n++;
    const delta = value - this.mean;
    this.mean += delta / this.n;
    this.m2 += delta * (value - this.mean);
    this.min = Math.min(this.min, value); this.max = Math.max(this.max, value);
    if (this.groundTruth !== null) this.absoluteError += Math.abs(value - this.groundTruth);
  }
  summary() {
    const bias = this.n && this.groundTruth !== null ? this.mean - this.groundTruth : null;
    return {
      sample_count: this.n,
      mean_raw_distance_m: this.n ? this.mean : null,
      total_stdev_m: this.n > 1 ? Math.sqrt(Math.max(0, this.m2 / (this.n - 1))) : null,
      min_raw_distance_m: this.n ? this.min : null,
      max_raw_distance_m: this.n ? this.max : null,
      mean_error_m: bias,
      mean_absolute_error_m: bias !== null ? this.absoluteError / this.n : null,
      rmse_m: bias !== null ? Math.sqrt(Math.max(0, this.m2 / this.n + bias * bias)) : null,
    };
  }
}
