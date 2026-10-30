import type { FrameSize } from './camera-settings';

export type NativeSettings = {
  index: number;
  width: number;
  height: number;
  fps: number;
  fourcc: string;
  backend: string;
};

async function errorFrom(response: Response): Promise<Error> {
  try {
    const body = await response.json() as { detail?: string };
    return new Error(body.detail || `Camera request failed (${response.status})`);
  } catch {
    return new Error(`Camera request failed (${response.status})`);
  }
}

export async function startNativeCamera(index: number, size: FrameSize | null): Promise<NativeSettings> {
  const response = await fetch('/api/native-camera/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({index, width: size?.width ?? null, height: size?.height ?? null, fps: 30})
  });
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<NativeSettings>;
}

export async function stopNativeCamera(): Promise<void> {
  try { await fetch('/api/native-camera/stop', {method: 'POST'}); } catch { /* server may already be gone */ }
}

export async function nativeFrame(format: 'jpeg'|'png' = 'jpeg'): Promise<Blob> {
  const response = await fetch(`/api/native-camera/frame?format=${format}&quality=95`, {cache: 'no-store'});
  if (!response.ok) throw await errorFrom(response);
  return response.blob();
}

export async function drawBlob(canvas: HTMLCanvasElement, blob: Blob): Promise<void> {
  const bitmap = await createImageBitmap(blob);
  try {
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Canvas unavailable.');
    ctx.drawImage(bitmap, 0, 0);
  } finally {
    bitmap.close();
  }
}
