import test from "node:test";
import assert from "node:assert/strict";
import { parseOptimizerSeed, retainLockedIds, curveGeometry } from "./optimizer-state.js";

test("种子严格限制无符号32位整数文本，不接受空值或科学计数", () => {
  assert.equal(parseOptimizerSeed("0"), 0);
  assert.equal(parseOptimizerSeed("4294967295"), 4294967295);
  assert.equal(parseOptimizerSeed("0042"), 42);
  for (const value of ["", " ", "-1", "1.2", "1e3", "4294967296", "9007199254740993", 42, null]) {
    assert.equal(parseOptimizerSeed(value), null);
  }
});

test("队伍移除或跨标签替换后锁定项只能来自现有成员", () => {
  assert.deepEqual(retainLockedIds([25, 6, 25, 260], [260, 25, 143]), [25, 260]);
  assert.deepEqual(retainLockedIds([25], []), []);
  assert.deepEqual(retainLockedIds([260, 6], [6, 25, 260]), [6, 260]);
});

test("曲线使用真实代数并处理固定分数及仅评分场景", () => {
  const curve = curveGeometry([{ generation: 0, best: 80, mean: 60 }, { generation: 100, best: 95, mean: 90 }]);
  assert.equal(curve.lastGeneration, 100);
  assert.ok(curve.best.startsWith("0.00,"));
  assert.ok(curve.best.includes("600.00,"));
  assert.ok(curve.low <= 60 && curve.high >= 95);
  for (const score of [0, 100]) {
    const one = curveGeometry([{ generation: 0, best: score, mean: score }]);
    assert.ok(!one.best.includes("NaN") && !one.best.includes("Infinity"));
    assert.ok(one.high > one.low);
  }
  assert.equal(curveGeometry([]), null);
});
