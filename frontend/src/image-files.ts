/** Decode once, without scaling; retain the source file separately for EXIF/provenance. */
export async function loadImage(file: File): Promise<HTMLCanvasElement> {
  if (file.size > 100_000_000) throw new Error('Image exceeds 100 MB.');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url; await image.decode();
    const w = image.naturalWidth, h = image.naturalHeight;
    if (!w || !h || Math.max(w,h)>12000 || w*h>60_000_000) throw new Error('Image exceeds 12000 pixels per side or 60 MP.');
    const canvas = document.createElement('canvas'); canvas.width=w; canvas.height=h;
    canvas.getContext('2d')!.drawImage(image,0,0); return canvas;
  } catch(e) { throw new Error(e instanceof Error ? e.message : 'Cannot decode image. Export camera RAW/HEIF files as JPEG or PNG first.'); }
  finally { URL.revokeObjectURL(url); }
}
export function png(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Image encoding failed.')),'image/png'));
}
export function copyCanvas(source: HTMLCanvasElement): HTMLCanvasElement {
  const copy=document.createElement('canvas');copy.width=source.width;copy.height=source.height;
  copy.getContext('2d')!.drawImage(source,0,0);return copy;
}
/** Uncompressed ZIP: one download keeps images and JSON together. */
export async function downloadArchive(files: {name:string;blob:Blob}[], filename:string): Promise<void> {
  const parts: BlobPart[] = [], directory: BlobPart[] = []; let offset=0, directorySize=0;
  for(const file of files){
    const bytes=new Uint8Array(await file.blob.arrayBuffer()), name=new TextEncoder().encode(file.name);
    let crc=0xffffffff;
    for(const byte of bytes){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
    crc=(crc^0xffffffff)>>>0;
    const header=new Uint8Array(30+name.length), h=new DataView(header.buffer);
    h.setUint32(0,0x04034b50,true);h.setUint16(4,20,true);h.setUint16(6,0x800,true);
    h.setUint32(14,crc,true);h.setUint32(18,bytes.length,true);h.setUint32(22,bytes.length,true);h.setUint16(26,name.length,true);header.set(name,30);
    const central=new Uint8Array(46+name.length), c=new DataView(central.buffer);
    c.setUint32(0,0x02014b50,true);c.setUint16(4,20,true);c.setUint16(6,20,true);c.setUint16(8,0x800,true);
    c.setUint32(16,crc,true);c.setUint32(20,bytes.length,true);c.setUint32(24,bytes.length,true);c.setUint16(28,name.length,true);c.setUint32(42,offset,true);central.set(name,46);
    parts.push(header,bytes);directory.push(central);offset+=header.length+bytes.length;directorySize+=central.length;
  }
  const end=new Uint8Array(22),e=new DataView(end.buffer);e.setUint32(0,0x06054b50,true);e.setUint16(8,files.length,true);e.setUint16(10,files.length,true);e.setUint32(12,directorySize,true);e.setUint32(16,offset,true);
  const url=URL.createObjectURL(new Blob([...parts,...directory,end],{type:'application/zip'}));
  const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),60_000);
}
