import test from 'node:test';
import assert from 'node:assert/strict';
import { downloadArchive } from '../.testbuild/image-files.js';

test('frame bundle contains valid stored ZIP entries and CRC',async()=>{
 let archive, clicked=false;
 const oldURL=URL.createObjectURL,oldTimer=globalThis.setTimeout,oldDocument=globalThis.document;
 URL.createObjectURL=blob=>{archive=blob;return 'blob:test';};
 globalThis.document={createElement:()=>({click(){clicked=true;}})};
 globalThis.setTimeout=()=>0;
 try{
  await downloadArchive([{name:'metadata.json',blob:new Blob(['123456789'])},{name:'annotated.png',blob:new Blob([new Uint8Array([1,2,3])])}], 'frame.zip');
  const bytes=new Uint8Array(await archive.arrayBuffer()),view=new DataView(bytes.buffer);
  assert.ok(clicked);assert.equal(view.getUint32(0,true),0x04034b50);
  assert.equal(view.getUint32(14,true),0xcbf43926); // Known CRC-32 vector.
  assert.equal(new TextDecoder().decode(bytes.slice(30,43)),'metadata.json');
  const end=bytes.length-22;assert.equal(view.getUint32(end,true),0x06054b50);
  assert.equal(view.getUint16(end+10,true),2);
  const central=view.getUint32(end+16,true);assert.equal(view.getUint32(central,true),0x02014b50);
  assert.equal(view.getUint32(central+42,true),0);
 }finally{URL.createObjectURL=oldURL;globalThis.setTimeout=oldTimer;globalThis.document=oldDocument;}
});
