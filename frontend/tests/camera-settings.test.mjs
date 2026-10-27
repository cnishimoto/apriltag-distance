import test from 'node:test';
import assert from 'node:assert/strict';
import {parseResolution,videoConstraints,captureError} from '../.testbuild/camera-settings.js';
test('Auto does not force a capture size',()=>{assert.equal(parseResolution('auto','',''),null);assert.deepEqual(videoConstraints('',null),{});});
test('presets and custom dimensions produce exact requests',()=>{
 assert.deepEqual(parseResolution('1920x1080','',''),{width:1920,height:1080});
 const size=parseResolution('custom','1024','768');
 assert.deepEqual(videoConstraints('fuji',size),{deviceId:{exact:'fuji'},width:{exact:1024},height:{exact:768}});
});
test('invalid custom sizes fail before opening a camera',()=>{
 for(const [w,h]of [['','720'],['0','720'],['1280.5','720'],['4097','720'],['abc','720'],['1280','-1']])assert.throws(()=>parseResolution('custom',w,h));
 assert.throws(()=>parseResolution('640x480x1','',''));
});
test('unsupported modes give an actionable Auto fallback',()=>{
 const error=new Error('constraints');error.name='OverconstrainedError';assert.match(captureError(error),/Choose Auto/);
});
