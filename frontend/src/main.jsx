import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import {
  BookOpen,
  MessageCircle,
  Users,
  Database,
  Search,
  ChevronLeft,
  ChevronRight,
  Plus,
  X,
  Send,
  Settings,
  Download,
  ArrowUpRight,
  Check,
  RefreshCw,
  ShieldCheck,
  FlaskConical,
  Trash2,
  CircleHelp,
  Leaf,
  Flame,
  Droplets,
  Zap,
  Snowflake,
  Wind,
  Bug,
  Mountain,
  Sparkles,
  Circle,
  Swords,
  Skull,
  Moon,
  Hexagon,
  Feather,
  Eye,
  LoaderCircle,
  Star,
  LayoutGrid,
  List,
  RotateCcw,
} from "lucide-react";
import "./style.css";
import { parseIds, readIds, pageNumbers, evolutionLayers } from "./pokedex-state.js";
import Workshop from "./Workshop.jsx";
import TeamOptimizer from "./TeamOptimizer.jsx";

const detailCache = new Map();

const TYPE_COLORS = {
  normal: "#777c88",
  fighting: "#b9593b",
  flying: "#7397ba",
  poison: "#9766b0",
  ground: "#ba9755",
  rock: "#a18c57",
  bug: "#819b46",
  ghost: "#756895",
  steel: "#6b8d98",
  fire: "#df7153",
  water: "#5098cd",
  grass: "#5d9b6c",
  electric: "#c9a32e",
  psychic: "#d57696",
  ice: "#63acb1",
  dragon: "#706eb4",
  dark: "#6e6871",
  fairy: "#c884ac",
};
const TYPE_ICONS = {
  grass: Leaf,
  fire: Flame,
  water: Droplets,
  electric: Zap,
  ice: Snowflake,
  flying: Feather,
  bug: Bug,
  ground: Mountain,
  rock: Mountain,
  fairy: Sparkles,
  fighting: Swords,
  poison: Skull,
  ghost: Moon,
  steel: Hexagon,
  psychic: Eye,
  dragon: Wind,
  dark: Moon,
};
const STATS = [
  ["hp", "HP", "#74b282"],
  ["attack", "攻击", "#df7b79"],
  ["defense", "防御", "#d9b75f"],
  ["sp_attack", "特攻", "#73a8d4"],
  ["sp_defense", "特防", "#6bb6bd"],
  ["speed", "速度", "#aa88cb"],
];
const EXAMPLES = [
  "皮卡丘的种族值是多少？",
  "列出第一世代所有火属性宝可梦",
  "水和地面双属性有哪些弱点？",
  "伊布有哪些进化形态？",
];
const NAV = [
  { id: "dex", name: "图鉴", icon: BookOpen },
  { id: "chat", name: "问答", icon: MessageCircle },
  { id: "team", name: "队伍", icon: Users },
  { id: "workshop", name: "创作", icon: Sparkles },
  { id: "data", name: "数据", icon: Database },
];
const number = (id) => `#${String(id).padStart(4, "0")}`;
async function api(path, body, signal) {
  const r = await fetch(`/api${path}`, {
    signal,
    ...(body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  }).catch((error) => {
    if (error.name === "AbortError") throw error;
    throw new Error("无法连接本地服务，请确认服务正在运行后重试。");
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "请求未完成，请稍后重试。",
    );
  return data;
}
function TypeBadge({ type }) {
  const Icon = TYPE_ICONS[type.name_en] || Circle;
  return (
    <span
      className="type-badge"
      style={{ "--type": TYPE_COLORS[type.name_en] || "#777c88" }}
    >
      <Icon size={11} />
      {type.name}
    </span>
  );
}
function Art({ pokemon, className = "", detail = false, priority = false }) {
  const [error, setError] = useState(null);
  const stage = error?.id === pokemon.id ? error.stage : 0;
  const size = detail ? 512 : 256;
  return stage >= 2 ? (
    <div className={`art-fallback ${className}`}>
      <BookOpen size={32} />
      <small>图像暂不可用</small>
    </div>
  ) : (
    <img
      key={`${pokemon.id}-${size}-${stage}`}
      className={`pokemon-art ${className}`}
      src={
        stage === 1
          ? pokemon.artwork
          : `/api/artwork/${pokemon.id}?size=${size}&v=1`
      }
      alt={pokemon.name}
      width={detail ? 475 : 256}
      height={detail ? 475 : 256}
      loading={priority ? "eager" : "lazy"}
      fetchPriority={detail ? "high" : "auto"}
      decoding="async"
      onError={() => setError({ id: pokemon.id, stage: stage + 1 })}
    />
  );
}
function IconButton({ title, children, ...props }) {
  return (
    <button
      className="icon-button"
      type="button"
      title={title}
      aria-label={title}
      {...props}
    >
      {children}
    </button>
  );
}
function ErrorNotice({ children, onRetry }) {
  return (
    <div className="notice error" role="alert">
      <CircleHelp size={17} />
      <span>{children}</span>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}
function PokemonCard({ pokemon, selected, onSelect, priority, favorite, onFavorite, viewed, member }) {
  return (
    <article
      className={`pokemon-card ${selected ? "selected" : ""}`}
      style={{"--card-type": TYPE_COLORS[pokemon.types[0]?.name_en] || "#777c88"}}
    >
      <button className="pokemon-card-main" onClick={() => onSelect(pokemon.id)} aria-label={`查看${pokemon.name}`} aria-pressed={selected}>
        <span className="dex-number">{number(pokemon.id)}</span>
        <Art pokemon={pokemon} priority={priority} />
        <span className="card-identity"><strong>{pokemon.name}</strong><small className="card-english">{pokemon.name_en}</small></span>
        <span className="type-row">{pokemon.types.map((t) => <TypeBadge key={t.id} type={t} />)}</span>
        <span className="card-total">种族值 <b>{pokemon.total}</b></span>
      </button>
      <button className={`favorite-button ${favorite ? "is-favorite" : ""}`} title={favorite ? `取消收藏${pokemon.name}` : `收藏${pokemon.name}`} aria-label={favorite ? `取消收藏${pokemon.name}` : `收藏${pokemon.name}`} aria-pressed={favorite} onClick={() => onFavorite(pokemon.id)}><Star size={17} fill={favorite ? "currentColor" : "none"}/></button>
      {(viewed || member) && <span className="card-record" title={member ? "已在队伍" : "已浏览"}>{member ? <Users size={12}/> : <Eye size={12}/>}</span>}
    </article>
  );
}
function download(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

function Inspector({ id, onSelect, onClose, onAsk, onAdd, team, favorite, onFavorite, onViewed, modal, isActive }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [tab, setTab] = useState("profile"),
    [retry, setRetry] = useState(0);
  const panel = useRef(null), closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const c = new AbortController();
    panel.current?.scrollTo({top:0});
    setData(detailCache.get(id) || null);
    setError("");
    if (detailCache.has(id)) {
      onViewed(id);
      return () => c.abort();
    }
    api(`/pokemon/${id}`, null, c.signal)
      .then((record) => {
        if (c.signal.aborted) return;
        if (detailCache.size >= 64) detailCache.delete(detailCache.keys().next().value);
        detailCache.set(id, record);
        setData(record);
        onViewed(id);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, [id, retry, onViewed]);
  useEffect(() => {
    if (!isActive) return;
    const previous = document.activeElement;
    const controls = () => [...panel.current.querySelectorAll('button:not(:disabled),a[href],summary,[tabindex="0"]')];
    if (modal) controls()[0]?.focus();
    const handle = (event) => {
      if (event.key === "Escape") closeRef.current();
      if (!modal || event.key !== "Tab") return;
      const items = controls(), first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {event.preventDefault();last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault();first?.focus();}
    };
    window.addEventListener("keydown", handle);
    return () => {
      window.removeEventListener("keydown", handle);
      if (modal && previous?.isConnected && previous.offsetParent !== null) previous.focus();
    };
  }, [modal, isActive]);
  const added = team.includes(id);
  return (
    <aside ref={panel} className="inspector" aria-label="宝可梦详情" role={modal ? "dialog" : undefined} aria-modal={modal || undefined}>
      <div className="inspector-top">
        <span className="dex-number">{number(id)}</span>
        <div className="button-row">
          <IconButton
            title="上一只"
            disabled={id <= 1}
            onClick={() => onSelect(id - 1)}
          >
            <ChevronLeft size={18} />
          </IconButton>
          <IconButton
            title="下一只"
            disabled={id >= 1025}
            onClick={() => onSelect(id + 1)}
          >
            <ChevronRight size={18} />
          </IconButton>
          <IconButton title="关闭详情" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </div>
      </div>
      {error ? (
        <ErrorNotice onRetry={() => setRetry((n) => n + 1)}>{error}</ErrorNotice>
      ) : !data || data.id !== id ? (
        <div className="loading">
          <LoaderCircle className="spin" />
          正在读取图鉴
        </div>
      ) : (
        <>
          <div
            className="detail-art"
            style={{
              "--art-tint": TYPE_COLORS[data.types[0]?.name_en] || "#888",
            }}
          >
            <span className="technical-mark">POKÉDEX RECORD</span>
            <Art pokemon={data} detail priority />
            <button className={`favorite-button detail-favorite ${favorite ? "is-favorite" : ""}`} title={favorite ? "取消收藏" : "收藏宝可梦"} aria-label={favorite ? "取消收藏" : "收藏宝可梦"} aria-pressed={favorite} onClick={() => onFavorite(id)}><Star size={20} fill={favorite ? "currentColor" : "none"}/></button>
            <span className="generation-mark">
              GEN {String(data.generation).padStart(2, "0")}
            </span>
          </div>
          <div className="detail-name">
            <div>
              <h2>{data.name}</h2>
              <span className="english-name">{data.name_en}</span>
            </div>
            <div className="type-row">
              {data.types.map((t) => (
                <TypeBadge key={t.id} type={t} />
              ))}
            </div>
          </div>
          <div className="detail-tabs" role="tablist" aria-label="详情分类" onKeyDown={(event) => {
            const tabs = ["profile", "evolution", "defense"];
            const index = tabs.indexOf(tab);
            const next = event.key === "ArrowRight" ? (index + 1) % 3 : event.key === "ArrowLeft" ? (index + 2) % 3 : event.key === "Home" ? 0 : event.key === "End" ? 2 : null;
            if (next === null) return;
            event.preventDefault();
            setTab(tabs[next]);
            event.currentTarget.querySelector(`[data-tab="${tabs[next]}"]`)?.focus();
          }}>
            {[
              ["profile", "资料"],
              ["evolution", "进化"],
              ["defense", "防御"],
            ].map(([v, l]) => (
              <button
                role="tab"
                id={`detail-tab-${v}`}
                data-tab={v}
                tabIndex={tab === v ? 0 : -1}
                aria-controls="detail-tabpanel"
                aria-selected={tab === v}
                key={v}
                onClick={() => setTab(v)}
              >
                {l}
              </button>
            ))}
          </div>
          <div role="tabpanel" id="detail-tabpanel" aria-labelledby={`detail-tab-${tab}`}>
          {tab === "profile" && (
            <>
              <div className="bio-grid">
                <div>
                  <label>分类</label>
                  <span>{data.genus || "未收录"}</span>
                </div>
                <div>
                  <label>身高 / 体重</label>
                  <span>
                    {data.height} m / {data.weight} kg
                  </span>
                </div>
                <div className="wide">
                  <label>特性</label>
                  <span>
                    {data.abilities
                      .map((a) => `${a.name}${a.is_hidden ? "（隐藏）" : ""}`)
                      .join(" · ") || "未收录"}
                  </span>
                </div>
              </div>
              <div className="section-heading">
                <h3>种族值</h3>
                <span>
                  总和 <b>{data.total}</b>
                </span>
              </div>
              <div className="stats">
                {STATS.map(([key, label, color]) => (
                  <div className="stat" key={key}>
                    <span>{label}</span>
                    <b>{data.stats[key]}</b>
                    <div className="stat-track">
                      <i
                        style={{
                          width: `${(data.stats[key] / 255) * 100}%`,
                          background: color,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <div className="description">
                <h3>图鉴记录</h3>
                <p>{data.description || "当前快照暂无描述。"}</p>
                <small>
                  {data.description_version} · {data.description_language}
                </small>
              </div>
              <div className="ability-records">
                <h3>特性记录</h3>
                {data.abilities.map((ability) => <details key={ability.id}>
                  <summary>{ability.name}{ability.is_hidden && <span>隐藏特性</span>}</summary>
                  <p>{ability.effect || "当前快照暂无说明。"}</p>
                  <small>{ability.language === "zh-hans" ? "简体中文" : "英语回退"}</small>
                </details>)}
              </div>
            </>
          )}
          {tab === "evolution" && (
            <div className="evolution-list">
              {data.evolution.length > 1 ? (
                evolutionLayers(data.evolution).map((layer, index) => <div className="evolution-stage" key={index}>
                  <h3>{index === 0 ? "基础阶段" : `第 ${index} 次进化`}</h3>
                  {layer.map((p) => <button key={p.id} className={`evolution-item ${p.id === id ? "current" : ""}`} onClick={() => onSelect(p.id)}>
                    <Art pokemon={p}/><span><small>{number(p.id)}</small><strong>{p.name}</strong>{p.from && <small>由 {data.evolution.find((parent) => parent.id === p.from)?.name || number(p.from)} 进化</small>}</span><ChevronRight size={16}/>
                  </button>)}
                </div>)
              ) : (
                <p>当前快照未收录其他进化关联。</p>
              )}
              <p className="muted small">
                按物种关系展示；具体进化条件以游戏版本为准。
              </p>
            </div>
          )}
          {tab === "defense" && (
            <div className="defense-panel">
              <h3>受到攻击时的属性倍率</h3>
              <div className="defense-grid">
                {data.defense.map((d) => (
                  <div key={d.type_id}>
                    <span>{d.type_name}</span>
                    <b
                      className={`multiplier m${String(d.multiplier).replace(".", "_")}`}
                    >
                      {d.multiplier}×
                    </b>
                  </div>
                ))}
              </div>
              <p className="muted small">
                仅计算属性。未计入特性、道具、天气和太晶化。
              </p>
            </div>
          )}
          </div>
          <div className="detail-actions">
            <button
              className="primary"
              onClick={() => onAsk(`介绍一下${data.name}`)}
            >
              <MessageCircle size={16} />
              向博士提问
            </button>
            <IconButton
              title={added ? "已在队伍" : team.length >= 6 ? "队伍已满（最多 6 只）" : "加入队伍"}
              disabled={added || team.length >= 6}
              onClick={() => onAdd(id)}
            >
              {added ? <Check size={19} /> : <Plus size={19} />}
            </IconButton>
          </div>
          <a
            className="source-link"
            href={data.source_url}
            target="_blank"
            rel="noreferrer"
          >
            PokeAPI 原始记录
            <ArrowUpRight size={12} />
          </a>
        </>
      )}
    </aside>
  );
}

function Catalog({ status, types, selected, onSelect, onAsk, onAdd, team, favorites, viewed, onFavorite, onViewed, modal, isActive }) {
  const [search, setSearch] = useState(""),
    [type, setType] = useState(""),
    [type2, setType2] = useState(""),
    [generation, setGeneration] = useState(""),
    [scope, setScope] = useState("all"),
    [sort, setSort] = useState("number"),
    [layout, setLayout] = useState("grid"),
    [page, setPage] = useState(1),
    [result, setResult] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0);
  const scrollArea = useRef(null);
  const collectionIds = scope === "favorites" ? favorites.join(",") : scope === "viewed" ? viewed.join(",") : null;
  useEffect(() => {
    const c = new AbortController();
    setBusy(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({
        search,
        page: String(page),
        limit: "24",
        sort,
      });
      if (type) params.set("type", type);
      if (type2) params.set("type2", type2);
      if (generation) params.set("generation", generation);
      if (collectionIds !== null) params.set("ids", collectionIds);
      api(`/pokemon?${params}`, null, c.signal)
        .then((r) => {
          if (c.signal.aborted) return;
          if (page > r.pages) { setPage(r.pages); return; }
          setResult(r);
          setError("");
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!c.signal.aborted) setBusy(false);
        });
    }, 180);
    return () => {
      clearTimeout(timer);
      c.abort();
    };
  }, [search, type, type2, generation, page, reload, sort, collectionIds]);
  useEffect(() => { scrollArea.current?.scrollTo({ top: 0 }); }, [page]);
  const filter = (setter) => (e) => {
    setter(e.target.value);
    setPage(1);
  };
  function resetFilters() {
    setSearch(""); setType(""); setType2(""); setGeneration(""); setSort("number"); setPage(1);
  }
  const filtered = search || type || type2 || generation;
  return (
    <div className={`catalog-layout ${selected ? "with-inspector" : ""}`}>
      <section ref={scrollArea} className="catalog" inert={modal && selected ? true : undefined}>
        <div className="page-title">
          <div>
            <h1>全国图鉴</h1>
            <span className="count">{status?.pokemon_count || "—"} 个物种</span>
          </div>
          <span className="edition">GENERATION I · IX</span>
        </div>
        <div className="collection-tabs" aria-label="图鉴范围">
          {[["all", "全部", status?.pokemon_count ?? "—"], ["favorites", "收藏", favorites.length], ["viewed", "已浏览", viewed.length]].map(([key, label, count]) => <button key={key} className={scope === key ? "active" : ""} aria-pressed={scope === key} onClick={() => {setScope(key);setPage(1);}}>{label}<span>{count}</span></button>)}
        </div>
        <div className="filters">
          <label className="search-field">
            <Search size={18} />
            <input
              aria-label="搜索宝可梦"
              maxLength={100}
              placeholder="搜索名称或图鉴编号"
              value={search}
              onChange={filter(setSearch)}
            />
            {search && (
              <IconButton
                title="清除搜索"
                onClick={() => {
                  setSearch("");
                  setPage(1);
                }}
              >
                <X size={14} />
              </IconButton>
            )}
          </label>
          <select aria-label="属性筛选" value={type} onChange={filter(setType)}>
            <option value="">所有属性</option>
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <select aria-label="第二属性筛选" value={type2} onChange={filter(setType2)}>
            <option value="">第二属性不限</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <select
            aria-label="世代筛选"
            value={generation}
            onChange={filter(setGeneration)}
          >
            <option value="">所有世代</option>
            {Array.from({ length: 9 }, (_, i) => (
              <option key={i} value={i + 1}>
                第 {i + 1} 世代
              </option>
            ))}
          </select>
          <IconButton title="重置筛选" onClick={resetFilters} disabled={!filtered && sort === "number"}><RotateCcw size={17}/></IconButton>
        </div>
        <div className="catalog-controls">
          <label>排序 <select aria-label="图鉴排序" value={sort} onChange={filter(setSort)}>
            <option value="number">图鉴编号升序</option><option value="id_desc">图鉴编号降序</option><option value="total_desc">种族值从高到低</option><option value="speed_desc">速度从高到低</option>
          </select></label>
          <div className="view-switch" aria-label="显示方式">
            <button title="网格视图" aria-label="网格视图" aria-pressed={layout === "grid"} className={layout === "grid" ? "active" : ""} onClick={() => setLayout("grid")}><LayoutGrid size={18}/></button>
            <button title="列表视图" aria-label="列表视图" aria-pressed={layout === "list"} className={layout === "list" ? "active" : ""} onClick={() => setLayout("list")}><List size={18}/></button>
          </div>
        </div>
        <div className="catalog-meta">
          <span aria-live="polite">
            {filtered ? "筛选结果" : "默认形态"}{" "}
            <b>{result?.total ?? "—"}</b>
          </span>
          <span>{busy ? "读取中…" : type && type2 && type !== type2 ? "同时满足两个属性" : "点击卡片查看详情"}</span>
        </div>
        {scope !== "all" && <p className="collection-note">{scope === "favorites" ? "收藏" : "浏览记录"}仅保存在此浏览器中。</p>}
        {error ? (
          <ErrorNotice onRetry={() => setReload((x) => x + 1)}>
            {error}
          </ErrorNotice>
        ) : result?.items.length === 0 ? (
          <div className="empty-state">
            <Search size={32} />
            <h2>{scope !== "all" && !collectionIds ? scope === "favorites" ? "还没有收藏的宝可梦" : "还没有浏览记录" : "没有找到匹配的宝可梦"}</h2>
            <button
              className="text-button"
              onClick={() => {
                resetFilters();
                if (!collectionIds) setScope("all");
              }}
            >
              {scope !== "all" && !collectionIds ? "浏览全部图鉴" : "清除筛选"}
            </button>
          </div>
        ) : (
          <div
            className={`pokemon-grid ${layout === "list" ? "list-mode" : ""} ${busy ? "fetching" : ""}`}
            aria-busy={busy}
          >
            {!result && Array.from({length: 8}, (_, index) => <div className="catalog-skeleton" key={index} aria-hidden="true"/>)}
            {result?.items.map((p, index) => (
              <PokemonCard
                key={p.id}
                pokemon={p}
                selected={selected === p.id}
                onSelect={onSelect}
                priority={index < 8}
                favorite={favorites.includes(p.id)}
                onFavorite={onFavorite}
                viewed={viewed.includes(p.id)}
                member={team.includes(p.id)}
              />
            ))}
          </div>
        )}
        {result?.total > 0 && (
          <div className="pagination">
            <span>
              第 {page} / {result.pages} 页
            </span>
            <div className="button-row">
              <IconButton
                title="上一页"
                disabled={page === 1 || busy}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft size={19} />
              </IconButton>
              {pageNumbers(page, result.pages).map((n, index, numbers) => <React.Fragment key={n}>
                {index > 0 && n - numbers[index - 1] > 1 && <span aria-hidden="true">…</span>}
                <button className={`page-number ${page === n ? "active" : ""}`} aria-label={`第 ${n} 页`} aria-current={page === n ? "page" : undefined} disabled={busy} onClick={() => setPage(n)}>{n}</button>
              </React.Fragment>)}
              <IconButton
                title="下一页"
                disabled={page >= result.pages || busy}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight size={19} />
              </IconButton>
            </div>
          </div>
        )}
      </section>
      {selected && (
        <Inspector
          id={selected}
          onSelect={onSelect}
          onClose={() => onSelect(null)}
          onAsk={onAsk}
          onAdd={onAdd}
          team={team}
          favorite={favorites.includes(selected)}
          onFavorite={onFavorite}
          onViewed={onViewed}
          modal={modal}
          isActive={isActive}
        />
      )}
    </div>
  );
}

function Answer({ message, onSelect }) {
  const r = message.result;
  const [visible, setVisible] = useState(24);
  return (
    <article className="answer">
      <div className="answer-byline">
        <span className="professor-avatar">
          <FlaskConical size={18} />
        </span>
        <strong>大木博士</strong>
        <span className="engine-label">
          {r.engine === "llm" ? "模型生成" : "证据回答"}
        </span>
        <small>{r.latency_ms?.toFixed?.(0) ?? r.latency_ms} ms</small>
        <IconButton
          title="导出这条问答"
          onClick={() =>
            download("pokedex-answer.json", {
              question: message.question,
              ...r,
            })
          }
        >
          <Download size={15} />
        </IconButton>
      </div>
      <div className="answer-text">{r.answer}</div>
      {r.warnings?.length > 0 && (
        <div className="answer-warnings">
          {r.warnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </div>
      )}
      {r.pokemon?.length > 0 && (
        <div className="answer-results">
          <div className="section-heading">
            <h3>相关图鉴</h3>
            <span>{r.total ?? r.pokemon.length} 条</span>
          </div>
          <div className="answer-pokemon">
            {r.pokemon.slice(0, visible).map((p) => (
              <button key={p.id} onClick={() => onSelect(p.id)}>
                <Art pokemon={p} />
                <span>
                  <small>{number(p.id)}</small>
                  <strong>{p.name}</strong>
                </span>
                <ArrowUpRight size={14} />
              </button>
            ))}
          </div>
          {r.pokemon.length > visible && <button className="text-button" onClick={() => setVisible((n) => n + 24)}>显示更多图鉴（已显示 {visible} / {r.pokemon.length}）</button>}
        </div>
      )}
      <div className="answer-details">
        <details>
          <summary>
            检索与执行过程{" "}
            <span>
              {r.mode} · {r.intent}
            </span>
          </summary>
          <ol>
            {r.trace?.map((t, i) => (
              <li key={i}>
                <strong>{t.step}</strong>
                <p>{t.detail}</p>
              </li>
            ))}
          </ol>
        </details>
        <details>
          <summary>
            引用来源 <span>{r.evidence?.length || 0} 条</span>
          </summary>
          <div className="evidence-list">
            {r.evidence?.map((e, i) => (
              <div key={`${e.id}-${i}`}>
                <a href={e.url} target="_blank" rel="noreferrer">
                  [{e.id}] {e.title}
                  <ArrowUpRight size={13} />
                </a>
                <p>{e.text}</p>
                <small>{e.kind}</small>
              </div>
            ))}
          </div>
        </details>
      </div>
    </article>
  );
}
function Chat({ initialQuestion, onInitialConsumed, onSelect, isActive = true }) {
  const [question, setQuestion] = useState(""),
    [messages, setMessages] = useState([]),
    [mode, setMode] = useState("R2"),
    [busy, setBusy] = useState(false),
    [pending, setPending] = useState(null),
    [failed, setFailed] = useState(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const scroll = useRef(null),
    active = useRef(null),
    input = useRef(null);
  async function ask(q, requestedMode = mode) {
    const text = q.trim();
    if (!text || active.current) return;
    const request = {
      controller: new AbortController(),
      question: text,
      mode: requestedMode,
    };
    active.current = request;
    setBusy(true);
    setPending({ question: text, mode: requestedMode });
    setError("");
    setNotice("");
    setFailed(null);
    setQuestion((draft) => (draft.trim() === text ? "" : draft));
    try {
      const result = await api(
        "/ask",
        { question: text, mode: requestedMode },
        request.controller.signal,
      );
      if (active.current !== request) return;
      setMessages((m) => [...m, { question: text, result }]);
    } catch (e) {
      if (active.current !== request) return;
      if (e.name !== "AbortError") {
        setError(e.message);
        setFailed({ question: text, mode: requestedMode });
      }
      setQuestion((draft) => (draft.trim() ? draft : text));
    } finally {
      if (active.current === request) {
        active.current = null;
        setBusy(false);
        setPending(null);
      }
    }
  }
  function cancel() {
    const request = active.current;
    if (!request) return;
    active.current = null;
    request.controller.abort();
    setBusy(false);
    setPending(null);
    setError("");
    setFailed(null);
    setQuestion((draft) => (draft.trim() ? draft : request.question));
    setNotice("已取消页面等待；不能保证服务端已经停止处理此请求。");
  }
  useEffect(() => {
    if (initialQuestion) {
      setQuestion(initialQuestion);
      onInitialConsumed();
      if (isActive && !active.current) input.current?.focus();
    }
  }, [initialQuestion, onInitialConsumed, isActive]);
  useEffect(() => {
    if (!isActive || !scroll.current) return;
    scroll.current.scrollTo({
      top: scroll.current.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [messages, pending, isActive]);
  useEffect(() => () => {
    const request = active.current;
    active.current = null;
    request?.controller.abort();
  }, []);
  return (
    <section className="chat-page">
      <div className="page-title">
        <div>
          <h1>博士问答</h1>
          <span className="count">研究室</span>
        </div>
        <div className="button-row">
          <select
            aria-label="检索方案"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            disabled={busy}
          >
            <option value="R2">R2 完整性校验</option>
            <option value="R1">R1 结构化检索</option>
            <option value="R0">R0 文本检索</option>
          </select>
          <IconButton
            title="导出全部已完成问答"
            disabled={!messages.length}
            onClick={() => download("pokedex-conversation.json", {
              exported_at: new Date().toISOString(),
              scope: "独立提问，不继承上一轮条件",
              messages,
            })}
          >
            <Download size={17} />
          </IconButton>
          <IconButton
            title="清空对话"
            disabled={busy || !messages.length}
            onClick={() => {
              if (!active.current && window.confirm("清空全部已完成问答？此操作无法撤销，输入草稿会保留。")) {
                setMessages([]);
                setError("");
                setFailed(null);
                setNotice("");
              }
            }}
          >
            <Trash2 size={17} />
          </IconButton>
        </div>
      </div>
      <div className="chat-scroll" ref={scroll}>
        {messages.length === 0 && !busy ? (
          <div className="chat-welcome">
            <div className="research-emblem">
              <FlaskConical size={37} />
            </div>
            <h2>每一次好奇，都值得探索。</h2>
            <p>宝可梦研究室 · 大木博士</p>
            <div className="question-suggestions">
              {EXAMPLES.map((q, i) => (
                <button key={q} onClick={() => ask(q)}>
                  <span className="example-index">0{i + 1}</span>
                  <span>{q}</span>
                  <ArrowUpRight size={16} />
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <div className="chat-turn" key={i}>
              <div className="user-question">{m.question}</div>
              <Answer message={m} onSelect={onSelect} />
            </div>
          ))
        )}
        {pending && (
          <div className="chat-turn">
            <div className="user-question">{pending.question}</div>
            <div className="thinking" role="status">
              <LoaderCircle size={18} className="spin" />
              <span>正在检索知识与核对规则…</span>
              <IconButton title="取消等待" onClick={cancel}>
                <X size={18} />
              </IconButton>
            </div>
            <p className="muted small">
              取消仅停止页面等待，服务端可能仍会继续处理请求。
            </p>
          </div>
        )}
      </div>
      <div className="composer-area">
        {error && (
          <ErrorNotice onRetry={failed ? () => ask(failed.question, failed.mode) : undefined}>
            {error}
          </ErrorNotice>
        )}
        {notice && <div className="notice" role="status">{notice}</div>}
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
        >
          <textarea
            ref={input}
            aria-label="向博士提问"
            placeholder="向博士提问…"
            maxLength={1000}
            rows={2}
            value={question}
            disabled={busy}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                ask(question);
              }
            }}
          />
          <button
            className="send-button"
            title="发送问题"
            aria-label="发送问题"
            disabled={!question.trim() || busy}
          >
            {busy ? (
              <LoaderCircle className="spin" size={20} />
            ) : (
              <Send size={20} />
            )}
          </button>
        </form>
        <div className="composer-footer">
          <span>
            <ShieldCheck size={12} />
            事实与计算以本地快照为依据
          </span>
          <span>独立提问 · 不继承上一轮条件</span>
        </div>
      </div>
    </section>
  );
}

function Team({ team, onRemove, onBrowse, onSelect, onApply }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [retry, setRetry] = useState(0),
    [weaknessOnly, setWeaknessOnly] = useState(false);
  useEffect(() => {
    setData(null);
    setError("");
    if (!team.length) {
      setBusy(false);
      return;
    }
    const c = new AbortController();
    setBusy(true);
    api("/team", { pokemon_ids: team }, c.signal)
      .then((result) => { if (!c.signal.aborted) setData(result); })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setBusy(false);
      });
    return () => c.abort();
  }, [team, retry]);
  return (
    <section className="team-page">
      <div className="page-title">
        <div>
          <h1>我的队伍</h1>
          <span className="count">{team.length} / 6</span>
        </div>
        <button
          className="primary"
          onClick={onBrowse}
          disabled={team.length >= 6}
        >
          <Plus size={16} />
          添加成员
        </button>
      </div>
      <div className="scope-note">
        <ShieldCheck size={17} />
        属性防御分析 · 不包含特性、道具、天气、太晶化或配招
      </div>
      <TeamOptimizer api={api} team={team} currentMembers={data?.members || []} onApply={onApply} onSelect={onSelect} Art={Art} TypeBadge={TypeBadge} download={download} />
      {error && (
        <ErrorNotice onRetry={() => setRetry((v) => v + 1)}>
          {error}
        </ErrorNotice>
      )}
      {!team.length ? (
        <div className="empty-state">
          <Users size={40} />
          <h2>队伍还没有成员</h2>
          <button className="primary" onClick={onBrowse}>
            前往图鉴
            <ArrowUpRight size={16} />
          </button>
        </div>
      ) : busy ? (
        <div className="loading">
          <LoaderCircle className="spin" />
          正在计算属性倍率
        </div>
      ) : (
        data &&
        !error && (
          <>
            <div className="team-members">
              {data.members.map((p) => (
                <article key={p.id} className="team-member">
                  <IconButton
                    title={`移除${p.name}`}
                    onClick={() => onRemove(p.id)}
                  >
                    <X size={15} />
                  </IconButton>
                  <button
                    className="team-member-main"
                    onClick={() => onSelect(p.id)}
                  >
                    <Art pokemon={p} />
                    <small>{number(p.id)}</small>
                    <h3>{p.name}</h3>
                  </button>
                  <div className="type-row">
                    {p.types.map((t) => (
                      <TypeBadge type={t} key={t.id} />
                    ))}
                  </div>
                </article>
              ))}
              {Array.from({length: 6 - data.members.length}, (_, index) => <button key={`empty-${index}`} className="team-empty-slot" onClick={onBrowse} aria-label={`添加第 ${data.members.length + index + 1} 位成员`}><Plus size={24}/><span>空位 {data.members.length + index + 1}</span></button>)}
            </div>
            <div className="section-heading large">
              <h2>防御属性矩阵</h2>
              <IconButton
                title="导出队伍分析"
                onClick={() => download("pokedex-team.json", data)}
              >
                <Download size={18} />
              </IconButton>
            </div>
            <label className="matrix-filter"><input type="checkbox" checked={weaknessOnly} onChange={(event) => setWeaknessOnly(event.target.checked)}/>只看队伍的弱点属性</label>
            <p className="muted small">横向滚动可查看全部成员。弱点数为受到大于 1 倍伤害的成员数量。</p>
            <div className="table-scroll">
              <table className="matchup-table">
                <thead>
                  <tr>
                    <th>攻击属性</th>
                    {data.members.map((p) => (
                      <th key={p.id}>{p.name}</th>
                    ))}
                    <th>弱点数</th>
                  </tr>
                </thead>
                <tbody>
                  {data.matchups.filter((m) => !weaknessOnly || m.weak_count > 0).map((m) => (
                    <tr key={m.type_id}>
                      <th>{m.type_name}</th>
                      {m.multipliers.map((n, i) => (
                        <td key={i}>
                          <span
                            className={`multiplier m${String(n).replace(".", "_")}`}
                          >
                            {n}×
                          </span>
                        </td>
                      ))}
                      <td className={m.weak_count > 2 ? "danger-text" : ""}>
                        {m.weak_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="team-summary">
              <h3>分析记录</h3>
              <p>
                {typeof data.summary === "string"
                  ? data.summary
                  : JSON.stringify(data.summary)}
              </p>
              {data.warnings?.map((w, i) => (
                <p className="muted" key={i}>
                  {w}
                </p>
              ))}
            </div>
          </>
        )
      )}
    </section>
  );
}
function DataPage({ status, onRefresh }) {
  return (
    <section className="data-page">
      <div className="page-title">
        <div>
          <h1>知识库</h1>
          <span className="count">本地快照</span>
        </div>
        <IconButton title="刷新数据状态" onClick={onRefresh}>
          <RefreshCw size={18} />
        </IconButton>
      </div>
      <div className="data-summary">
        <div>
          <span>默认形态物种</span>
          <strong>{status?.pokemon_count ?? "—"}</strong>
        </div>
        <div>
          <span>知识文档</span>
          <strong>{status?.document_count ?? "—"}</strong>
        </div>
        <div>
          <span>常规属性</span>
          <strong>18</strong>
        </div>
      </div>
      <h2>数据与检索</h2>
      <dl className="metadata">
        <dt>数据源</dt>
        <dd>
          <a
            href="https://github.com/PokeAPI/pokeapi"
            target="_blank"
            rel="noreferrer"
          >
            PokeAPI / pokeapi
            <ArrowUpRight size={13} />
          </a>
        </dd>
        <dt>快照版本</dt>
        <dd>
          {typeof status?.data_version === "object"
            ? JSON.stringify(status.data_version)
            : status?.data_version || "正在读取"}
        </dd>
        <dt>检索引擎</dt>
        <dd>
          {typeof status?.retrieval === "object"
            ? JSON.stringify(status.retrieval)
            : status?.retrieval || "正在读取"}
        </dd>
        <dt>生成模型</dt>
        <dd>
          {status?.model?.configured
            ? status.model.name ||
              status.model.model ||
              "已配置，调用时验证连接"
            : "未配置 · 使用确定性证据回答"}
        </dd>
        <dt>结构化计算</dt>
        <dd>SQLite 条件查询 · NetworkX 进化关系 · 属性倍率乘积</dd>
        <dt>来源关系</dt>
        <dd>
          文本、关系与结构化字段来自同一 PokeAPI 上游，不构成独立来源交叉验证。
        </dd>
        <dt>版本边界</dt>
        <dd>
          当前快照的默认形态与现代 18
          属性规则；不是任意历史游戏版本的完整数据库。
        </dd>
      </dl>
      <h2>使用边界</h2>
      <div className="data-notes">
        <p>
          本项目用于课程学习与研究，非官方产品。宝可梦名称、形象及相关素材版权归各权利人所有。
        </p>
        <p>
          图片原始来源为 PokeAPI sprites 仓库，优先读取本地缓存。
          数据库快照存于本地。描述缺失时保留英文回退与语言标识。
        </p>
        <p>
          问题、检索证据只在配置并启用生成模型后发送到指定模型服务。未配置时不调用付费模型。
        </p>
      </div>
      <a
        className="source-link"
        href="/api/status"
        target="_blank"
        rel="noreferrer"
      >
        查看完整运行状态
        <ArrowUpRight size={13} />
      </a>
    </section>
  );
}

function App() {
  const [view, setView] = useState("dex"),
    [status, setStatus] = useState(null),
    [types, setTypes] = useState([]),
    [compact, setCompact] = useState(() => window.innerWidth <= 900),
    [favorites, setFavorites] = useState(() => readIds("pokedex-favorites")),
    [viewed, setViewed] = useState(() => readIds("pokedex-viewed")),
    [selected, setSelected] = useState(() =>
      window.innerWidth > 900 ? 1 : null,
    ),
    [team, setTeam] = useState(() => readIds("pokedex-team", 6)),
    [initialQuestion, setInitialQuestion] = useState(""),
    [statusError, setStatusError] = useState(""),
    [settings, setSettings] = useState(false),
    [toast, setToast] = useState("");
  async function refresh() {
    try {
      setStatus(await api("/status"));
      setStatusError("");
      setTypes(await api("/types"));
    } catch (e) {
      setStatusError(e.message);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const change = () => setCompact(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("pokedex-team", JSON.stringify(team));
    } catch { setToast("浏览器无法保存队伍，仅在本次打开期间保留。"); }
  }, [team]);
  useEffect(() => {
    try {
      localStorage.setItem("pokedex-favorites", JSON.stringify(favorites));
    } catch { setToast("浏览器无法保存收藏，仅在本次打开期间保留。"); }
  }, [favorites]);
  useEffect(() => {
    try {
      localStorage.setItem("pokedex-viewed", JSON.stringify(viewed));
    } catch { setToast("浏览器无法保存浏览记录，仅在本次打开期间保留。"); }
  }, [viewed]);
  useEffect(() => {
    const sync = (event) => {
      const target = {"pokedex-team": [setTeam, 6], "pokedex-favorites": [setFavorites, 1025], "pokedex-viewed": [setViewed, 1025]}[event.key];
      if (!target) return;
      const ids = parseIds(event.newValue, target[1]);
      target[0]((previous) => previous.join(",") === ids.join(",") ? previous : ids);
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  const markViewed = useCallback((id) => setViewed((ids) => ids.includes(id) ? ids : [...ids, id]), []);
  const toggleFavorite = useCallback((id) => setFavorites((ids) => ids.includes(id) ? ids.filter((n) => n !== id) : [...ids, id]), []);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 2500);
      return () => clearTimeout(t);
    }
  }, [toast]);
  useEffect(() => {
    if (!settings) return;
    const previous = document.activeElement;
    const dialog = document.querySelector(".settings-modal");
    const controls = () =>
      Array.from(
        dialog.querySelectorAll(
          'button:not(:disabled),a[href],input,select,textarea,[tabindex="0"]',
        ),
      );
    controls()[0]?.focus();
    const close = (e) => {
      if (e.key === "Escape") setSettings(false);
      if (e.key === "Tab") {
        const items = controls();
        const first = items[0],
          last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("keydown", close);
      previous?.focus();
    };
  }, [settings]);
  function add(id) {
    if (team.includes(id) || team.length >= 6) return;
    setTeam((t) => t.includes(id) || t.length >= 6 ? t : [...t, id]);
    setToast("已加入队伍");
  }
  function openPokemon(id) {
    setSelected(id);
    setView("dex");
  }
  function ask(q) {
    setInitialQuestion(q);
    setView("chat");
  }
  return (
    <div className="app">
      <nav className="nav-rail" aria-label="主导航" inert={settings || (compact && selected && view === "dex") ? true : undefined}>
        <button
          className="brand-symbol"
          aria-label="返回图鉴"
          title="宝可梦图鉴"
          onClick={() => setView("dex")}
        >
          <span />
        </button>
        <div className="nav-items">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={view === n.id ? "active" : ""}
              onClick={() => setView(n.id)}
              aria-current={view === n.id ? "page" : undefined}
              title={n.name}
            >
              <n.icon size={23} />
              <span>{n.name}</span>
              {n.id === "team" && team.length > 0 && <i>{team.length}</i>}
            </button>
          ))}
        </div>
        <div className="rail-bottom">
          <span className="rail-dot" />
          <span>LAB 01</span>
        </div>
      </nav>
      <header className="app-header" inert={settings || (compact && selected && view === "dex") ? true : undefined}>
        <div className="brand-text">
          <strong>
            宝可梦图鉴<span className="brand-slash"> / </span>
            <span className="brand-subtitle">大木博士研究室</span>
          </strong>
          <small>POKÉDEX · RESEARCH EDITION</small>
        </div>
        <div className="header-right">
          <span className="online-status">
            <i
              className={
                statusError || status?.ready === false ? "offline" : ""
              }
            />
            {statusError
              ? "连接异常"
              : status?.ready
                ? "本地知识库已就绪"
                : status
                  ? "知识库未就绪"
                  : "正在连接"}
          </span>
          <IconButton title="运行设置" onClick={() => setSettings(true)}>
            <Settings size={20} />
          </IconButton>
        </div>
      </header>
      <main className={`workspace view-${view}`} inert={settings || undefined}>
        {statusError && (
          <div className="global-error">
            <ErrorNotice onRetry={refresh}>{statusError}</ErrorNotice>
          </div>
        )}
        <div hidden={view !== "dex"} className="view-container">
          <Catalog
            status={status}
            types={types}
            selected={selected}
            onSelect={setSelected}
            onAsk={ask}
            onAdd={add}
            team={team}
            favorites={favorites}
            viewed={viewed}
            onFavorite={toggleFavorite}
            onViewed={markViewed}
            modal={compact}
            isActive={view === "dex" && !settings}
          />
        </div>
        <div hidden={view !== "chat"} className="view-container">
          <Chat
            isActive={view === "chat"}
            initialQuestion={initialQuestion}
            onInitialConsumed={() => setInitialQuestion("")}
            onSelect={openPokemon}
          />
        </div>
        {view === "team" && (
          <Team
            team={team}
            onRemove={(id) => setTeam((t) => t.filter((x) => x !== id))}
            onApply={(ids) => setTeam(ids)}
            onBrowse={() => setView("dex")}
            onSelect={openPokemon}
          />
        )}{" "}
        <div hidden={view !== "workshop"} className="view-container">
          <Workshop api={api} isActive={view === "workshop"} />
        </div>
        {view === "data" && <DataPage status={status} onRefresh={refresh} />}
      </main>
      {toast && (
        <div className="toast" role="status">
          <Check size={16} />
          {toast}
        </div>
      )}
      {settings && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSettings(false);
          }}
        >
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
          >
            <div className="section-heading">
              <h2 id="settings-title">运行设置</h2>
              <IconButton title="关闭设置" onClick={() => setSettings(false)}>
                <X size={20} />
              </IconButton>
            </div>
            <dl>
              <dt>生成模式</dt>
              <dd>
                {status?.model?.configured ? "已配置模型服务" : "本地证据回答"}
              </dd>
              <dt>模型</dt>
              <dd>{status?.model?.name || status?.model?.model || "未配置"}</dd>
              <dt>检索</dt>
              <dd>
                {typeof status?.retrieval === "object"
                  ? JSON.stringify(status.retrieval)
                  : status?.retrieval || "—"}
              </dd>
            </dl>
            <p className="muted">
              模型连接由服务端环境变量配置。API 密钥不会保存到浏览器。
            </p>
            <button
              className="primary"
              onClick={() => {
                setSettings(false);
                setView("data");
              }}
            >
              <Database size={16} />
              查看知识库状态
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
