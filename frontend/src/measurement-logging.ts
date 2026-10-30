import type { FrameResult, TagMeasurement } from './types';
import { groundTruthValue, TrialStatistics, newRecordId } from './trial-statistics.js';

const field = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
type CurrentFrame = { id: string; tag: TagMeasurement | undefined; result: FrameResult; metadata: Record<string, unknown> };
export type MeasurementRecord = { metadata: Record<string, unknown>; row: Record<string, unknown> | null };

export class MeasurementLogging {
  private truth = field<HTMLInputElement>('groundTruth');
  private label = field<HTMLInputElement>('trialLabel');
  private target = field<HTMLSelectElement>('logSelect');
  private appendButton = field<HTMLButtonElement>('appendMeasurement');
  private auto = field<HTMLInputElement>('logOnSave');
  private message = field<HTMLElement>('loggingStatus');
  private token = '';
  private current: CurrentFrame | null = null;
  private trial = new TrialStatistics(null);
  private trialId = newRecordId();
  private trialStarted = new Date().toISOString();
  private trialTag: number | null = null;
  private busy = false;
  private pending: { record: MeasurementRecord; target: string } | null = null;

  constructor() {
    this.truth.oninput = () => this.reset('Ground truth changed. New trial starts with the displayed frame.');
    this.label.onchange = () => this.reset('Trial label changed. New trial starts with the displayed frame.');
    field<HTMLButtonElement>('resetTrial').onclick = () => this.reset('New trial started with the displayed frame.');
    this.target.onchange = () => this.controls();
    field<HTMLButtonElement>('refreshLogs').onclick = () => this.action(async () => this.refresh());
    field<HTMLButtonElement>('createLog').onclick = () => this.action(async () => {
      const name = this.logName();
      await this.request('/api/logs', { method: 'POST', body: JSON.stringify({ name }) });
      await this.refresh(name); this.say(`Created ${name}. Select a valid measurement to append a row.`);
    });
    const input = field<HTMLInputElement>('importLog');
    input.onchange = () => this.action(async () => {
      const file = input.files?.[0]; if (!file) return;
      try {
        if (file.size > 25_000_000) throw new Error('CSV exceeds 25 MB.');
        const name = this.logName(file.name);
        await this.request(`/api/logs/import?name=${encodeURIComponent(name)}`, { method: 'POST', body: file });
        await this.refresh(name); this.say(`Imported a local copy as ${name}. Your original file was not changed.`);
      } finally { input.value = ''; }
    });
    this.appendButton.onclick = () => this.action(async () => {
      const record = this.buildRecord(null); const target = this.target.value;
      await this.append(record, target);
    });
    field<HTMLButtonElement>('retryLog').onclick = () => this.action(async () => {
      if (this.pending) await this.append(this.pending.record, this.pending.target);
    });
    this.controls();
  }
  async initialize(token: string): Promise<void> { this.token = token; await this.refresh(); this.controls(); }
  private groundTruth(): number | null {
    if (this.truth.validity.badInput) throw new Error('Enter a positive ground-truth distance in meters, or clear the field.');
    return groundTruthValue(this.truth.value);
  }
  reset(message = '', seed = true): void {
    let truth: number | null = null;
    try { truth = this.groundTruth(); } catch { /* Invalid input disables export/logging below. */ }
    this.trial = new TrialStatistics(truth); this.trialId = newRecordId();
    this.trialStarted = new Date().toISOString(); this.trialTag = null;
    if (!seed) this.current = null;
    if (seed && this.current?.tag) {
      this.trialTag = this.current.tag.id;
      this.trial.add(this.current.tag.raw_distance_m, this.current.id);
    }
    if (message) this.say(message);
    this.controls();
  }
  observe(id: string, result: FrameResult, selectedId: string, metadata: Record<string, unknown>): void {
    const tag = result.tags.find(t => String(t.id) === selectedId);
    if (tag && this.trialTag !== null && this.trialTag !== tag.id) this.reset('', false);
    this.current = { id, tag, result, metadata };
    if (tag) { this.trialTag = tag.id; this.trial.add(tag.raw_distance_m, id); }
    this.controls();
  }
  clear(): void { this.reset('', false); }
  private controls(): void {
    let valid = true;
    try { this.groundTruth(); } catch { valid = false; }
    this.truth.setAttribute('aria-invalid', String(!valid));
    field('truthError').textContent = valid ? '' : 'Use a positive number in meters, or leave blank.';
    const summary = this.trial.summary();
    field('trialSummary').textContent = `${summary.sample_count} samples · Mean ${summary.mean_raw_distance_m?.toFixed(4) ?? '—'} m · Total SD ${summary.total_stdev_m?.toFixed(4) ?? '—'} m`;
    this.appendButton.disabled = this.busy || !this.token || !this.target.value || !valid || this.current?.tag?.raw_distance_m == null || this.current.tag.distance_m == null;
    field<HTMLButtonElement>('retryLog').disabled = this.busy || !this.pending;
    const link = field<HTMLAnchorElement>('downloadLog');
    link.hidden = !this.target.value;
    link.href = `/api/logs/${encodeURIComponent(this.target.value)}`;
    for (const id of ['createLog', 'refreshLogs', 'importLog']) (field(id) as HTMLButtonElement | HTMLInputElement).disabled = this.busy || !this.token;
  }
  private logName(fallback = ''): string {
    const input = field<HTMLInputElement>('newLogName').value.trim() || fallback;
    if (!input) throw new Error('Enter a name for the new spreadsheet.');
    return input.toLowerCase().endsWith('.csv') ? input : `${input}.csv`;
  }
  private say(text: string, error = false): void {
    this.message.textContent = text; this.message.dataset.tone = error ? 'error' : 'info';
  }
  private async action(work: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true; this.controls();
    try { await work(); } catch (e) { this.say(e instanceof Error ? e.message : String(e), true); }
    finally { this.busy = false; this.controls(); }
  }
  private async request(path: string, options: RequestInit = {}): Promise<Record<string, unknown>> {
    const response = await fetch(path, { ...options, headers: { 'x-log-token': this.token } });
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Spreadsheet request failed.');
    return value as Record<string, unknown>;
  }
  private async refresh(selected = this.target.value): Promise<void> {
    const response = await this.request('/api/logs');
    const names = response.logs as string[];
    this.target.replaceChildren(new Option('Choose a spreadsheet', ''), ...names.map(name => new Option(name, name)));
    if (names.includes(selected)) this.target.value = selected;
    field('logFolder').textContent = `Saved on this computer: ${String(response.folder)}`;
    this.controls();
  }
  targetForFrameDownload(): string | null {
    if (!this.auto.checked) return null;
    if (!this.target.value) throw new Error('Choose or create a spreadsheet, or turn off “Also append when downloading a frame”.');
    if (this.pending) throw new Error('Retry the pending spreadsheet row first, or turn off automatic spreadsheet logging.');
    return this.target.value;
  }
  buildRecord(archive: string | null): MeasurementRecord {
    const frame = this.current;
    if (!frame) throw new Error('Process an image or start the camera first.');
    const gt = this.groundTruth(); const tag = frame.tag; const stats = this.trial.summary();
    const recordId = newRecordId(); const loggedAt = new Date().toISOString();
    const distance = tag?.distance_m ?? null, raw = tag?.raw_distance_m ?? null;
    const error = distance !== null && gt !== null ? distance - gt : null;
    const metadata = { ...frame.metadata, schema_version: 2, record_id: recordId, frame_id: frame.id,
      selected_tag_id: tag?.id ?? null, ground_truth_m: gt, ground_truth_tag_id: tag?.id ?? null,
      ground_truth_definition: 'Euclidean distance from camera center to selected tag center, in meters.',
      trial_id: this.trialId, trial_label: this.label.value.trim(), trial_started_at_utc: this.trialStarted,
      statistics: stats, statistics_definition: 'All valid raw distances for the selected tag in this trial. Sample SD uses n-1; blank for n<2. No uncertainty or independence assumption.',
      error_m: error, absolute_error_m: error === null ? null : Math.abs(error),
      exported_at_utc: loggedAt, frame_archive: archive,
    };
    if (!tag || distance === null || raw === null || stats.sample_count === 0) return { metadata, row: null };
    const config = frame.metadata.config as { tag: { tag_size_m: number; dictionary: string; smoothing_alpha: number } };
    const source = frame.metadata.source as { kind?: string; label?: string; filename?: string };
    const row = {
      schema_version: 1, record_id: recordId, frame_id: frame.id, trial_id: this.trialId,
      logged_at_utc: loggedAt, captured_at_utc: frame.metadata.captured_at_utc,
      trial_label: this.label.value.trim(), tag_id: tag.id, ground_truth_m: gt,
      distance_m: distance, raw_distance_m: raw, error_m: error,
      absolute_error_m: error === null ? null : Math.abs(error), percent_error: error !== null && gt !== null ? 100 * error / gt : null,
      raw_error_m: gt !== null ? raw - gt : null, depth_m: tag.depth_m,
      ...stats, reprojection_error_px: tag.reprojection_error_px, processing_ms: frame.result.processing_ms,
      analysis_fps: frame.metadata.analysis_fps, image_width: frame.result.width, image_height: frame.result.height,
      source_kind: source.kind ?? '', source_name: source.filename ?? source.label ?? '',
      tag_size_m: config.tag.tag_size_m, dictionary: config.tag.dictionary, smoothing_alpha: config.tag.smoothing_alpha,
      warning: frame.result.warning ?? tag.note ?? '', frame_archive: archive ?? '', metadata_json: JSON.stringify(metadata),
    };
    return { metadata, row };
  }
  async append(record: MeasurementRecord, target: string): Promise<void> {
    if (!record.row) throw new Error('No valid selected-tag distance. The frame can still be downloaded with spreadsheet logging turned off.');
    if (!target) throw new Error('Choose a spreadsheet first.');
    if (this.pending && this.pending.record !== record) throw new Error('Retry the pending row before appending another measurement.');
    this.pending = { record, target };
    try {
      const result = await this.request(`/api/logs/${encodeURIComponent(target)}/rows`, { method: 'POST', body: JSON.stringify(record.row) });
      this.pending = null;
      this.say(`${result.duplicate ? 'Row already saved' : 'Row saved'} in ${target}. ${result.rows} rows total.`);
    } catch(e) {
      this.say('Spreadsheet save failed. Use Retry pending row to save this exact measurement without duplicating it.', true);
      throw e;
    } finally { this.controls(); }
  }
}
