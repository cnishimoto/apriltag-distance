import test from 'node:test';
import assert from 'node:assert/strict';
import { TrialStatistics, groundTruthValue } from '../.testbuild/trial-statistics.js';

test('known trial calculates sample SD, bias, MAE and RMSE',()=>{
 const trial=new TrialStatistics(2);
 [1,2,3].forEach((v,i)=>trial.add(v,String(i)));
 const s=trial.summary();
 assert.equal(s.sample_count,3);assert.equal(s.mean_raw_distance_m,2);
 assert.equal(s.total_stdev_m,1);assert.equal(s.mean_error_m,0);
 assert.equal(s.mean_absolute_error_m,2/3);assert.equal(s.rmse_m,Math.sqrt(2/3));
 assert.equal(s.min_raw_distance_m,1);assert.equal(s.max_raw_distance_m,3);
});
test('no truth, one sample, no measurement and duplicate display events',()=>{
 const trial=new TrialStatistics(null);
 assert.equal(trial.summary().total_stdev_m,null);
 trial.add(null,'a');trial.add(NaN,'b');assert.equal(trial.summary().sample_count,0);
 trial.add(2,'c');trial.add(2,'c');
 assert.equal(trial.summary().sample_count,1);assert.equal(trial.summary().total_stdev_m,null);
 assert.equal(trial.summary().mean_error_m,null);assert.equal(trial.summary().rmse_m,null);
 trial.add(2,'d');assert.equal(trial.summary().total_stdev_m,0);
});
test('ground truth is optional but must be finite and positive',()=>{
 assert.equal(groundTruthValue(''),null);assert.equal(groundTruthValue(' '),null);
 assert.equal(groundTruthValue('1.25'),1.25);
 for(const v of ['0','-1','NaN','Infinity','bad'])assert.throws(()=>groundTruthValue(v));
});
