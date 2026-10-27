/** Shared capture controls. Presets are requests, not a camera capability list. */
export type FrameSize = { width: number; height: number };
export function parseResolution(choice: string, width: string, height: string): FrameSize | null {
  if (choice === 'auto') return null;
  const values = choice === 'custom' ? [width, height] : choice.split('x');
  if (values.length !== 2 || values.some(v => !/^\d+$/.test(v))) {
    throw new Error('Enter a whole-number width and height.');
  }
  const [w, h] = values.map(Number);
  if (w < 1 || h < 1 || w > 4096 || h > 4096) {
    throw new Error('Width and height must each be between 1 and 4096 pixels.');
  }
  return { width: w, height: h };
}
export function videoConstraints(deviceId: string, size: FrameSize | null): MediaTrackConstraints {
  return {
    ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    ...(size ? { width: { exact: size.width }, height: { exact: size.height } } : {})
  };
}
export function captureError(error: unknown): string {
  if (!(error instanceof Error)) return String(error);
  const errors: Record<string, string> = {
    NotAllowedError: 'Camera permission was denied. Allow access in your browser, then try again.',
    NotFoundError: 'No camera found. Connect a camera, then refresh the page.',
    NotReadableError: 'The camera is busy or unavailable. Close other camera apps and try again.',
    OverconstrainedError: 'This camera cannot provide the requested settings. Choose Auto or a different resolution, then start again.'
  };
  return errors[error.name] || error.message;
}
export class ResolutionControl {
  private select: HTMLSelectElement;
  private width: HTMLInputElement;
  private height: HTMLInputElement;
  private fields: HTMLElement;
  constructor(onChange: () => void) {
    this.select = document.getElementById('resolutionSelect') as HTMLSelectElement;
    this.width = document.getElementById('customWidth') as HTMLInputElement;
    this.height = document.getElementById('customHeight') as HTMLInputElement;
    this.fields = document.getElementById('customResolution') as HTMLElement;
    this.select.addEventListener('change', () => {
      this.fields.hidden = this.select.value !== 'custom';
      onChange();
    });
    for (const field of [this.width, this.height]) field.addEventListener('change', onChange);
  }
  value(): FrameSize | null { return parseResolution(this.select.value, this.width.value, this.height.value); }
  disable(disabled: boolean): void {
    for (const field of [this.select, this.width, this.height]) field.disabled = disabled;
  }
  addCalibration(width: number, height: number): void {
    const option = new Option(`Saved calibration · ${width} × ${height}`, `${width}x${height}`);
    this.select.add(option, 1);
  }
}
