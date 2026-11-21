import test from "node:test";
import assert from "node:assert/strict";
import {parseIds, pageNumbers, evolutionLayers} from "./pokedex-state.js";

test("本机集合去重、过滤异常值且不误认字符串编号", () => {
  assert.deepEqual(parseIds('[25,25,6,"7",0,1026,null,1.5]'), [25,6]);
  for (const value of ['broken', '{}', 'null', null]) assert.deepEqual(parseIds(value), []);
  assert.deepEqual(parseIds('[1,2,3,4,5,6,7]',6), [1,2,3,4,5,6]);
});
test("分页在首尾与空结果时不产生无效页码", () => {
  assert.deepEqual(pageNumbers(1,43),[1,2,43]);
  assert.deepEqual(pageNumbers(42,43),[1,41,42,43]);
  assert.deepEqual(pageNumbers(1,1),[1]);
});
test("进化按父子关系而非编号，保留分支", () => {
  const layers = evolutionLayers([{id:25,from:172},{id:26,from:25},{id:172,from:null}]);
  assert.deepEqual(layers.map((row)=>row.map((p)=>p.id)),[[172],[25],[26]]);
  assert.deepEqual(evolutionLayers([{id:133,from:null},{id:134,from:133},{id:135,from:133}]).map((row)=>row.length),[1,2]);
  assert.deepEqual(evolutionLayers([{id:1,from:2},{id:2,from:1}]),[]);
});
