export function parseOptimizerSeed(value) {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return null;
  const seed = Number(value);
  return Number.isSafeInteger(seed) && seed <= 4294967295 ? seed : null;
}

export function retainLockedIds(lockedIds, team) {
  return [...new Set(lockedIds)].filter((id) => team.includes(id)).sort((a, b) => a - b);
}

export function curveGeometry(history, width = 600, height = 160) {
  if (!history.length) return null;
  const scores = history.flatMap((row) => [row.best, row.mean]);
  const low = Math.max(0, Math.floor(Math.min(...scores) / 5) * 5 - 5);
  const high = Math.min(100, Math.ceil(Math.max(...scores) / 5) * 5 + 5);
  const span = Math.max(1, high - low);
  const lastGeneration = history.at(-1).generation;
  const path = (field) => history.map((row) => {
    const x = lastGeneration ? row.generation / lastGeneration * width : 0;
    const y = height - (row[field] - low) / span * height;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  return { best: path("best"), mean: path("mean"), low, high, lastGeneration };
}
