import test from 'node:test';
import assert from 'node:assert/strict';
import { MeasurementLogging } from '../.testbuild/measurement-logging.js';
import { newRecordId } from '../.testbuild/trial-statistics.js';

function setup(){
 const elements=new Map();
 globalThis.document={getElementById(id){
  if(!elements.has(id))elements.set(id,{value:'',validity:{badInput:false},dataset:{},setAttribute(){},replaceChildren(){},disabled:false,checked:false});
  return elements.get(id);
 }};
 globalThis.Option=class {constructor(label,value){this.label=label;this.value=value;}};
 return elements;
}
function frame(distance=2,tagId=7){
 const tag={id:tagId,distance_m:distance,raw_distance_m:distance,depth_m:distance,reprojection_error_px:.2,corners:[],note:null};
 return {width:640,height:480,tags:[tag],processing_ms:5,warning:null};
}
const metadata={captured_at_utc:'2026-10-30T00:00:00Z',source:{kind:'camera',label:'Brio'},config:{tag:{tag_size_m:.16,dictionary:'DICT_APRILTAG_36h11',smoothing_alpha:.35}},analysis_fps:30};

test('frame records freeze truth and trial stats; selection/reference changes reset samples',()=>{
 const elements=setup(), logging=new MeasurementLogging();
 elements.get('groundTruth').value='2';elements.get('groundTruth').oninput();
 const id=newRecordId();logging.observe(id,frame(1),'7',metadata);
 logging.observe(id,frame(1),'7',metadata); // Selecting same tag must not add a sample.
 logging.observe(newRecordId(),frame(3),'7',metadata);
 const saved=logging.buildRecord('frame.zip');
 assert.equal(saved.row.sample_count,2);assert.equal(saved.row.total_stdev_m,Math.sqrt(2));
 assert.equal(saved.row.error_m,1);assert.equal(saved.metadata.ground_truth_m,2);
 assert.equal(saved.row.record_id,saved.metadata.record_id);
 assert.equal(JSON.parse(saved.row.metadata_json).frame_archive,'frame.zip');
 elements.get('groundTruth').value='4';elements.get('groundTruth').oninput();
 logging.observe(newRecordId(),frame(5),'7',metadata);
 assert.equal(saved.metadata.ground_truth_m,2);assert.equal(saved.row.sample_count,2);
 assert.notEqual(logging.buildRecord(null).metadata.trial_id,saved.metadata.trial_id);
 logging.observe(newRecordId(),frame(2,8),'8',metadata);
 assert.equal(logging.buildRecord(null).row.sample_count,1);
 assert.equal(logging.buildRecord(null).row.total_stdev_m,null);
 logging.clear();assert.throws(()=>logging.buildRecord(null));
});

test('optional reference, invalid distance and retry keep exact saved record',async()=>{
 const elements=setup(), logging=new MeasurementLogging();
 logging.observe(newRecordId(),frame(),'7',metadata);
 let record=logging.buildRecord(null);
 assert.equal(record.row.ground_truth_m,null);assert.equal(record.row.error_m,null);
 elements.get('groundTruth').value='-1';assert.throws(()=>logging.buildRecord(null));
 elements.get('groundTruth').value='';
 let attempts=[];
 globalThis.fetch=async(path,options)=>{
  attempts.push(JSON.parse(options.body));
  if(attempts.length===1)throw new Error('offline');
  return {ok:true,json:async()=>({rows:1,duplicate:true})};
 };
 await assert.rejects(()=>logging.append(record,'test.csv'));
 logging.observe(newRecordId(),frame(4),'7',metadata);
 await assert.rejects(()=>logging.append(logging.buildRecord(null),'test.csv'),/pending row/);
 await logging.append(record,'test.csv');
 assert.deepEqual(attempts[0],attempts[1]);assert.equal(attempts[1].distance_m,2);
 const invalid=frame();invalid.tags[0].distance_m=null;invalid.tags[0].raw_distance_m=null;
 logging.observe(newRecordId(),invalid,'7',metadata);
 assert.equal(logging.buildRecord(null).row,null);
});
