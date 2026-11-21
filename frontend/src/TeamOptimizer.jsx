import React, { useEffect, useRef, useState } from "react";
import { Dna, Play, LockKeyhole, Download, Check, LoaderCircle, AlertCircle } from "lucide-react";
import { curveGeometry, parseOptimizerSeed, retainLockedIds } from "./optimizer-state.js";
import "./TeamOptimizer.css";

function EvolutionCurve({ history }) {
  const curve = curveGeometry(history);
  if (!curve || history.length < 2) return <p className="optimizer-help">队伍已唯一确定，本次仅评分，没有运行进化搜索。</p>;
  return (
    <figure className="optimizer-curve">
      <figcaption><strong>进化过程</strong><span><i className="best" />历史最佳<i className="mean" />种群平均</span></figcaption>
      <div className="optimizer-plot">
        <div className="optimizer-y-axis"><span>{curve.high}</span><span>{(curve.high + curve.low) / 2}</span><span>{curve.low}</span></div>
        <svg viewBox="0 0 600 160" preserveAspectRatio="none" role="img" aria-label={`第0至${curve.lastGeneration}代评分曲线，最终最佳分${history.at(-1).best.toFixed(2)}`}>
          {[0, 80, 160].map((y) => <line key={y} x1="0" y1={y} x2="600" y2={y} className="optimizer-grid-line" />)}
          <polyline points={curve.mean} className="optimizer-mean-line" />
          <polyline points={curve.best} className="optimizer-best-line" />
        </svg>
      </div>
      <div className="optimizer-x-axis"><span>第 0 代</span><span>第 {curve.lastGeneration / 2} 代</span><span>第 {curve.lastGeneration} 代</span></div>
      <p className="optimizer-help">纵轴为本次评分范围；曲线来自实际计算，非对战胜率。</p>
    </figure>
  );
}

export default function TeamOptimizer({ api, team, currentMembers, onApply, onSelect, Art, TypeBadge, download }) {
  const [generation, setGeneration] = useState("");
  const [includeSpecial, setIncludeSpecial] = useState(false);
  const [lockedIds, setLockedIds] = useState([]);
  const [seed, setSeed] = useState("42");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeRequest = useRef(null);
  const requestSequence = useRef(0);
  const effectiveLocks = retainLockedIds(lockedIds, team);
  const requestKey = JSON.stringify([generation, includeSpecial, effectiveLocks, seed]);
  const latestKey = useRef(requestKey);
  latestKey.current = requestKey;
  const teamKey = team.join(",");
  const seedNumber = parseOptimizerSeed(seed);
  const visibleResult = result?.requestKey === requestKey ? result.data : null;
  const applied = visibleResult && team.length === 6 && visibleResult.pokemon_ids.every((id) => team.includes(id));
  const knownMembers = [...currentMembers, ...(visibleResult?.members || [])];

  useEffect(() => {
    setLockedIds((previous) => {
      const retained = retainLockedIds(previous, team);
      return retained.length === previous.length ? previous : retained;
    });
  }, [teamKey]);

  useEffect(() => {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    setBusy(false);
    setError("");
    setResult(null);
    return () => {
      requestSequence.current += 1;
      activeRequest.current?.abort();
      activeRequest.current = null;
    };
  }, [requestKey]);

  async function run(event) {
    event.preventDefault();
    if (activeRequest.current || seedNumber === null) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    const sequence = ++requestSequence.current;
    const startedKey = requestKey;
    const current = () => !controller.signal.aborted && sequence === requestSequence.current && latestKey.current === startedKey;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const data = await api("/team/optimize", {
        generation: generation ? Number(generation) : null,
        include_special: includeSpecial,
        locked_ids: effectiveLocks,
        seed: seedNumber,
      }, controller.signal);
      if (current()) setResult({ requestKey: startedKey, data });
    } catch (failure) {
      if (current()) setError(failure.message);
    } finally {
      if (current()) {
        activeRequest.current = null;
        setBusy(false);
      }
    }
  }

  function cancelWaiting() {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    setBusy(false);
    setError("已取消等待。服务端本次计算可能仍在完成，可重新开始。");
  }

  return (
    <section className="team-optimizer" aria-labelledby="team-optimizer-heading">
      <div className="optimizer-heading">
        <div><Dna size={21} /><h2 id="team-optimizer-heading">遗传算法组队</h2></div>
        <span>属性互补 · 可复现实验</span>
      </div>
      <p className="optimizer-intro">从候选宝可梦中搜索六名成员，兼顾抗性覆盖、共同弱点与种族值。可以先锁定喜欢的成员。</p>
      <form onSubmit={run} className="optimizer-form">
        <div className="optimizer-fields">
          <label htmlFor="optimizer-generation">首次登场世代
            <select id="optimizer-generation" value={generation} onChange={(event) => setGeneration(event.target.value)}>
              <option value="">全部世代</option>
              {Array.from({ length: 9 }, (_, index) => <option value={index + 1} key={index}>第 {index + 1} 世代首次登场</option>)}
            </select>
          </label>
          <label htmlFor="optimizer-seed">随机种子
            <input id="optimizer-seed" type="text" inputMode="numeric" value={seed} onChange={(event) => setSeed(event.target.value)} aria-invalid={seedNumber === null} aria-describedby="optimizer-seed-help" autoComplete="off" />
          </label>
          <label className="optimizer-checkbox"><input type="checkbox" checked={includeSpecial} onChange={(event) => setIncludeSpecial(event.target.checked)} />允许传说与幻之宝可梦</label>
        </div>
        <p id="optimizer-seed-help" className={`optimizer-help${seedNumber === null ? " optimizer-invalid" : ""}`}>{seedNumber === null ? "随机种子须为 0–4294967295 之间的整数。" : "相同条件和种子得到相同结果；世代筛选仍使用当前快照的 18 属性规则。"}</p>
        <fieldset className="optimizer-locks">
          <legend><LockKeyhole size={14} />锁定当前成员 <span>{effectiveLocks.length} / 6</span></legend>
          {team.length ? <div className="optimizer-lock-list">{team.map((id) => {
            const member = knownMembers.find((item) => item.id === id);
            return <label key={id} className={effectiveLocks.includes(id) ? "is-locked" : ""}><input type="checkbox" checked={effectiveLocks.includes(id)} onChange={(event) => setLockedIds((ids) => event.target.checked ? [...ids, id] : ids.filter((item) => item !== id))} />{member?.name || `#${String(id).padStart(4, "0")}`}</label>;
          })}</div> : <p className="optimizer-help">当前队伍为空，可直接生成；在图鉴加入成员后即可锁定。</p>}
        </fieldset>
        <div className="optimizer-run-row">
          <button type="submit" className="primary" disabled={busy || seedNumber === null}>{busy ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />}{busy ? "正在优化" : "开始优化"}</button>
          {busy ? <button type="button" className="optimizer-secondary" onClick={cancelWaiting}>取消等待</button> : <span className="optimizer-help">种群 80 · 进化 100 代 · 精英保留 2</span>}
        </div>
      </form>
      {busy && <p role="status" className="optimizer-pending">正在本机计算候选队伍；修改条件会取消本次等待。</p>}
      {error && <div className="optimizer-error" role="alert"><AlertCircle size={17} /><p>{error}<span>检查条件后点击“开始优化”重试。</span></p></div>}
      {visibleResult && <div className="optimizer-result" role="region" aria-label="组队优化结果">
        <div className="optimizer-result-heading" role="status">
          <div><span>本次推荐评分</span><strong>{visibleResult.score.toFixed(2)}<small>/ 100</small></strong></div>
          <p>{visibleResult.candidate_count} 个候选 · {visibleResult.evaluations.toLocaleString()} 次评价<br />实际耗时 {(visibleResult.elapsed_ms / 1000).toFixed(2)} 秒 · 种子 {visibleResult.parameters.seed}</p>
        </div>
        <div className="optimizer-components">
          <div><span>抗性与免疫覆盖</span><strong>{visibleResult.components.coverage_count} / 18</strong><small>贡献 {visibleResult.components.weighted.coverage.toFixed(2)} / 50 分</small></div>
          <div><span>同一属性最多弱点人数</span><strong>{visibleResult.components.max_weak_count} / 6</strong><small>安全项 {visibleResult.components.weighted.weakness_safety.toFixed(2)} / 25 分</small></div>
          <div><span>队伍种族值总和</span><strong>{visibleResult.components.stat_total.toLocaleString()}</strong><small>贡献 {visibleResult.components.weighted.stats.toFixed(2)} / 25 分</small></div>
        </div>
        <p className="optimizer-weakness"><strong>弱点最集中的属性：</strong>{visibleResult.components.worst_types.map((type) => type.type_name).join("、") || "无"}。2 倍与 4 倍弱点均计一名成员。</p>
        <div className="optimizer-members">{visibleResult.members.map((member) => <article key={member.id}>
          <button type="button" onClick={() => onSelect(member.id)} aria-label={`查看${member.name}详情`}><Art pokemon={member} /><small>#{String(member.id).padStart(4, "0")}{effectiveLocks.includes(member.id) ? " · 已锁定" : ""}</small><h3>{member.name}</h3></button>
          <div className="type-row">{member.types.map((type) => <TypeBadge key={type.id} type={type} />)}</div>
          <span className="optimizer-member-stat">种族值 {member.total}</span>
        </article>)}</div>
        <EvolutionCurve history={visibleResult.history} />
        <div className="optimizer-actions">
          <button type="button" className="primary" onClick={() => onApply([...visibleResult.pokemon_ids])} disabled={applied}><Check size={16} />{applied ? "已应用到队伍" : "应用到我的队伍"}</button>
          <button type="button" className="optimizer-secondary" onClick={() => download(`pokedex-optimization-seed-${visibleResult.parameters.seed}.json`, visibleResult)}><Download size={15} />导出实验 JSON</button>
        </div>
        <p className="optimizer-help">推荐结果仅作预览，点击应用才会替换队伍。数据版本：{visibleResult.data_version}</p>
        {visibleResult.warnings.map((warning, index) => <p className="optimizer-help" key={index}>{warning}</p>)}
      </div>}
      <details className="optimizer-method">
        <summary>评分与搜索规则</summary>
        <p>总分 = 50 × 抗性覆盖比例 + 25 × 共同弱点安全项 + 25 × 种族值比例。</p>
        <p>安全项 = 1 − max(0，同一属性最多弱点人数 − 2) / 4；种族值比例 = 队伍种族值总和 / 4320。权重预先固定；不计特性、招式与道具，不代表实战胜率。</p>
        <p>三人锦标赛选择，交叉概率 90%，后代变异概率 20%。锁定六名成员时只评分，不搜索；算法不保证全局最优。</p>
      </details>
    </section>
  );
}
