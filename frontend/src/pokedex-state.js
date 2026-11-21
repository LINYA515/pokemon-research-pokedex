export function parseIds(value, limit = 1025) {
  try {
    const ids = JSON.parse(value || "[]");
    return Array.isArray(ids)
      ? [...new Set(ids.filter((id) => Number.isInteger(id) && id >= 1 && id <= 1025))].slice(0, limit)
      : [];
  } catch {
    return [];
  }
}

export function readIds(key, limit) {
  try {
    return parseIds(localStorage.getItem(key), limit);
  } catch {
    return [];
  }
}

export function pageNumbers(page, pages) {
  return [...new Set([1, page - 1, page, page + 1, pages])]
    .filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
}

export function evolutionLayers(items) {
  const remaining = new Map(items.map((item) => [item.id, item]));
  const layers = [];
  // 按真实父子关系分层，不能把全国图鉴编号顺序当作进化顺序。
  while (remaining.size) {
    const layer = [...remaining.values()].filter((item) => !remaining.has(item.from));
    if (!layer.length) break;
    layers.push(layer);
    layer.forEach((item) => remaining.delete(item.id));
  }
  return layers;
}
