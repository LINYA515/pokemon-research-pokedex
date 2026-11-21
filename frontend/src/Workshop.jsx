import React, { useEffect, useRef, useState } from "react";
import { Sparkles, Flame, Droplets, Leaf, Zap, RefreshCw, ArrowUpRight, Download, LoaderCircle, Image, BookOpen, AlertCircle } from "lucide-react";
import "./Workshop.css";

const THEMES = [
  ["fire", "火焰", Flame, "#d36a4c"],
  ["water", "水流", Droplets, "#4a8fc0"],
  ["grass", "草木", Leaf, "#568d62"],
  ["electric", "雷电", Zap, "#aa8825"],
];
const LABELS = { queued: "等待生成", running: "正在生成", succeeded: "已完成", failed: "生成失败" };
const pending = (job) => job?.status === "queued" || job?.status === "running";
const mergeJob = (items, job) => [job, ...items.filter((item) => item.id !== job.id)];
const dateLabel = (value) => value ? new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";

function ResultImage({ job }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [job.id, job.image_url]);
  if (failed) return <div className="workshop-result-empty"><AlertCircle size={28} /><p>图片暂时无法读取</p><button className="workshop-secondary" onClick={() => setFailed(false)}>重新加载图片</button></div>;
  return <img src={job.image_url} alt={`创作 ${job.id} 的生成结果`} onError={() => setFailed(true)} />;
}

export default function Workshop({ api, isActive }) {
  const [requirements, setRequirements] = useState({ theme: "fire", body: "quadruped", stage: "juvenile" });
  const [service, setService] = useState(null);
  const [serviceError, setServiceError] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptMode, setPromptMode] = useState("enhanced");
  const [seed, setSeed] = useState("42");
  const [useLora, setUseLora] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [showReference, setShowReference] = useState(true);
  const [activeId, setActiveId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [previewRefresh, setPreviewRefresh] = useState(0);
  const [pollError, setPollError] = useState("");
  const mounted = useRef(false);
  const submission = useRef(null);
  const previewKey = useRef("");
  const requestKey = JSON.stringify(requirements);
  const previewCurrent = !!preview && previewKey.current === `${requestKey}:${previewRefresh}`;
  const selectedJob = jobs.find((job) => job.id === selectedId) || jobs[0];
  const seedValid = /^\d+$/.test(seed) && Number(seed) <= 4294967295;
  const modelReady = useLora ? service?.lora_ready && service?.base_ready : service?.base_ready;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; submission.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!isActive) return;
    const controller = new AbortController();
    setServiceError("");
    setHistoryError("");
    api("/generations/status", undefined, controller.signal).then((data) => {
      if (!controller.signal.aborted) setService(data);
    }).catch((error) => {
      if (!controller.signal.aborted) { setService(null); setServiceError(error.message); }
    });
    api("/generations", undefined, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      const items = data.items || [];
      setJobs(items);
      const running = items.find(pending);
      setActiveId(running?.id || null);
    }).catch((error) => { if (!controller.signal.aborted) setHistoryError(error.message); });
    return () => controller.abort();
  }, [api, isActive, refresh]);

  useEffect(() => {
    if (!isActive || (preview && previewKey.current === `${requestKey}:${previewRefresh}`)) return;
    const controller = new AbortController();
    setPreview(null);
    setPreviewBusy(true);
    setPreviewError("");
    api("/generations/preview", requirements, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setPreview(data);
      setPrompt(data.enhanced_prompt);
      setPromptMode("enhanced");
      previewKey.current = `${requestKey}:${previewRefresh}`;
    }).catch((error) => { if (!controller.signal.aborted) setPreviewError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setPreviewBusy(false); });
    return () => controller.abort();
  }, [api, isActive, requestKey, previewRefresh]);

  useEffect(() => {
    if (!isActive || !activeId) return;
    const controller = new AbortController();
    let timer;
    setPollError("");
    const poll = async () => {
      try {
        const job = await api(`/generations/${encodeURIComponent(activeId)}`, undefined, controller.signal);
        if (controller.signal.aborted) return;
        setJobs((items) => mergeJob(items, job));
        setPollError("");
        if (pending(job)) timer = setTimeout(poll, 1500);
        else setActiveId(null);
      } catch (error) {
        if (controller.signal.aborted) return;
        setPollError("暂时无法更新任务状态，正在重试。请勿重复提交。");
        timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [api, activeId, isActive]);

  async function generate(event) {
    event.preventDefault();
    if (submission.current || activeId || !previewCurrent || !modelReady || !seedValid || !prompt.trim()) return;
    const controller = new AbortController();
    submission.current = controller;
    setSubmitting(true);
    setSubmitError("");
    try {
      const job = await api("/generations", { ...requirements, prompt: prompt.trim(), seed: Number(seed), use_lora: useLora }, controller.signal);
      if (!mounted.current) return;
      setJobs((items) => mergeJob(items, job));
      setSelectedId(job.id);
      setShowReference(false);
      setActiveId(pending(job) ? job.id : null);
    } catch (error) {
      if (mounted.current && !controller.signal.aborted) { setSubmitError(error.message); setRefresh((value) => value + 1); }
    } finally {
      submission.current = null;
      if (mounted.current) setSubmitting(false);
    }
  }

  const update = (key, value) => { setRequirements((current) => ({ ...current, [key]: value })); setSubmitError(""); };
  return (
    <section className="workshop-page" aria-labelledby="workshop-title">
      <div className="workshop-heading">
        <div><h1 id="workshop-title">创作工坊</h1><p>从图鉴知识出发，设计你的新伙伴。</p></div>
        <button className="workshop-secondary" onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={15} />刷新状态</button>
      </div>
      <div className={`workshop-status ${service?.lora_ready ? "is-ready" : ""}`} role="status">
        <Sparkles size={19} />
        <div><strong>{serviceError ? "无法读取模型状态" : !service ? "正在检查生成服务" : service.lora_ready ? "LoRA 创作模型已就绪" : service.base_ready ? "基础模型已就绪 · LoRA 待接入" : "生成模型尚未就绪"}</strong>
          <p>{serviceError || service?.warning || (service?.lora_ready ? "可以使用已加载的创作模型生成概念图。" : "可先整理创作需求、查看参考资料并编辑提示词。LoRA 完成本机加载验证后即可使用。")}</p></div>
      </div>
      <div className="workshop-layout">
        <form className="workshop-controls" onSubmit={generate}>
          <div className="workshop-section-title"><span>01</span><h2>描述新伙伴</h2></div>
          <fieldset className="workshop-theme-field"><legend>视觉主题</legend><div className="workshop-themes">
            {THEMES.map(([key, label, Icon, color]) => <button type="button" key={key} style={{ "--theme-color": color }} aria-pressed={requirements.theme === key} className={requirements.theme === key ? "selected" : ""} onClick={() => update("theme", key)}><Icon size={20} /><span>{label}</span></button>)}
          </div></fieldset>
          <div className="workshop-pair">
            <label>身体形态<select value={requirements.body} onChange={(event) => update("body", event.target.value)}><option value="biped">双足</option><option value="quadruped">四足</option><option value="serpentine">蛇形</option></select></label>
            <label>成长阶段<select value={requirements.stage} onChange={(event) => update("stage", event.target.value)}><option value="juvenile">幼年期</option><option value="adult">成年期</option></select></label>
          </div>
          <div className="workshop-section-title"><span>02</span><h2>整理创作提示</h2></div>
          <div className="workshop-prompt-tabs" aria-label="提示词来源">
            <button type="button" aria-pressed={promptMode === "raw"} disabled={!preview || previewBusy} onClick={() => { setPrompt(preview.raw_prompt); setPromptMode("raw"); }}>原始描述</button>
            <button type="button" aria-pressed={promptMode === "enhanced"} disabled={!preview || previewBusy} onClick={() => { setPrompt(preview.enhanced_prompt); setPromptMode("enhanced"); }}><BookOpen size={14} />图鉴增强</button>
            {promptMode === "custom" && <span>已手动编辑</span>}
          </div>
          {previewBusy && <p className="workshop-inline" role="status"><LoaderCircle size={15} className="workshop-spin" />正在整理参考资料…</p>}
          {previewError && <div className="workshop-error" role="alert"><p>{previewError}</p><button type="button" onClick={() => setPreviewRefresh((value) => value + 1)}>重试</button></div>}
          <label className="workshop-prompt-label">生成提示词（可编辑）<textarea value={prompt} maxLength={2000} disabled={!preview || previewBusy} onChange={(event) => { setPrompt(event.target.value); setPromptMode("custom"); }} placeholder="选择创作条件后，提示词会显示在这里。" spellCheck={false} /></label>
          <p className="workshop-help">改变主题、形态或阶段会重新整理提示词。视觉主题是创作要求，不代表官方属性判定。</p>
          <p className="workshop-help">SD1.5 最多接受 77 个词元，过长提示会提示缩短。</p>
          {preview?.evidence?.length > 0 && <details className="workshop-evidence"><summary><BookOpen size={14} />查看图鉴参考 <span>{preview.evidence.length} 条</span></summary><div>{preview.evidence.map((item, index) => <article key={item.id || index}><strong>{item.title}</strong><p>{item.text}</p>{/^https?:\/\//.test(item.source || "") && <a href={item.source} target="_blank" rel="noreferrer">查看来源<ArrowUpRight size={12} /></a>}</article>)}</div><p className="workshop-help">参考资料提供已有物种的事实；新伙伴的造型属于创作设定。</p></details>}
          <div className="workshop-section-title"><span>03</span><h2>生成与保存</h2></div>
          <fieldset className="workshop-models"><legend>生成模型</legend><label><input type="radio" name="creation-model" checked={!useLora} onChange={() => setUseLora(false)} />基础模型 <small>未微调</small></label><label className={!service?.lora_ready ? "is-unavailable" : ""}><input type="radio" name="creation-model" checked={useLora} disabled={!service?.lora_ready} onChange={() => setUseLora(true)} />LoRA 创作 <small>{service?.lora_ready ? "已加载" : "待接入"}</small></label></fieldset>
          <label className="workshop-seed">随机种子<input type="text" inputMode="numeric" value={seed} maxLength={10} aria-invalid={!seedValid} onChange={(event) => setSeed(event.target.value)} /></label>
          {!seedValid && <p className="workshop-error" role="alert">种子须为 0 至 4294967295 的整数。</p>}
          {submitError && <p className="workshop-error" role="alert">{submitError}</p>}
          <button className="primary workshop-generate" type="submit" disabled={!modelReady || !previewCurrent || previewBusy || !prompt.trim() || !seedValid || submitting || !!activeId}>{submitting || activeId ? <LoaderCircle size={17} className="workshop-spin" /> : <Sparkles size={17} />}{submitting ? "正在提交…" : activeId ? "正在生成，请稍候" : modelReady ? "生成概念图" : "等待生成模型就绪"}</button>
          <p className="workshop-help">每次生成一张图片，结果与参数自动保存在本机。</p>
        </form>
        <div className="workshop-output">
          <div className="workshop-section-title"><span><Image size={17} /></span><h2>创作预览</h2>{showReference ? <small>示例预览</small> : selectedJob && <small>{LABELS[selectedJob.status] || selectedJob.status}</small>}</div>
          <div className="workshop-prompt-tabs" aria-label="预览内容">
            <button type="button" aria-pressed={showReference} onClick={() => setShowReference(true)}>图鉴参考示例</button>
            <button type="button" aria-pressed={!showReference} onClick={() => setShowReference(false)}>生成结果</button>
          </div>
          <div className={`workshop-canvas ${!showReference && selectedJob?.status === "succeeded" ? "has-result" : ""}`} aria-live="polite">
            {showReference && <figure className="workshop-reference"><img src="/api/artwork/25?size=512" alt="皮卡丘图鉴参考插画" /><figcaption><strong>皮卡丘 · 图鉴参考示例</strong><p>示例图片，非本项目生成结果</p><small>图片来源：PokeAPI / sprites · official-artwork</small></figcaption></figure>}
            {!showReference && !selectedJob && <div className="workshop-result-empty"><div className="workshop-empty-symbol"><Sparkles size={38} /></div><h3>你的新伙伴将在这里出现</h3><p>先准备创作提示，模型就绪后即可生成。<br />这里仅展示真实生成结果。</p></div>}
            {!showReference && selectedJob?.status === "succeeded" && selectedJob.image_url && <ResultImage job={selectedJob} />}
            {!showReference && selectedJob?.status === "succeeded" && !selectedJob.image_url && <div className="workshop-result-empty"><AlertCircle size={32} /><h3>生成图片暂不可用</h3><p>任务已结束，但尚未读取到图片位置。请刷新状态。</p></div>}
            {!showReference && selectedJob && pending(selectedJob) && <div className="workshop-result-empty"><LoaderCircle size={36} className="workshop-spin" /><h3>{LABELS[selectedJob.status]}</h3><p>生成任务正在本机运行，完成后会自动显示。<br />可以切换到其他页面，回来查看结果。</p></div>}
            {!showReference && selectedJob?.status === "failed" && <div className="workshop-result-empty"><AlertCircle size={34} /><h3>这次生成未完成</h3><p>{selectedJob.error || "请检查模型状态后重新尝试。"}</p></div>}
          </div>
          {pollError && <p className="workshop-error" role="status">{pollError}</p>}
          {!showReference && selectedJob && <div className="workshop-result-meta"><div><strong>创作 {selectedJob.id.slice(0, 8)}</strong><span>{selectedJob.use_lora ? "LoRA 创作" : "基础模型 · 未微调"} · 种子 {selectedJob.seed}</span><small>{dateLabel(selectedJob.created_at)}{Number.isFinite(selectedJob.duration_s) ? ` · ${selectedJob.duration_s.toFixed(1)} 秒` : ""}</small></div>{selectedJob.status === "succeeded" && selectedJob.image_url && <a className="workshop-secondary" href={selectedJob.image_url} download={`creation-${selectedJob.id}.png`}><Download size={15} />保存图片</a>}<details><summary>查看本次生成提示</summary><p>{selectedJob.prompt}</p></details></div>}
          <div className="workshop-history-heading"><h2>创作记录</h2><span>{jobs.length} 条</span></div>
          {historyError && <p className="workshop-error" role="alert">记录读取失败：{historyError}</p>}
          {!jobs.length && !historyError && <p className="workshop-history-empty">尚无创作记录。生成后，图片和创作参数会保留在这里。</p>}
          <div className="workshop-history">{jobs.map((job) => <button key={job.id} type="button" className={!showReference && selectedJob?.id === job.id ? "selected" : ""} onClick={() => { setSelectedId(job.id); setShowReference(false); }} aria-pressed={!showReference && selectedJob?.id === job.id}><span className="workshop-history-icon">{job.status === "succeeded" ? <Image size={20} /> : pending(job) ? <LoaderCircle size={20} className="workshop-spin" /> : <AlertCircle size={20} />}</span><span><strong>创作 {job.id.slice(0, 8)}</strong><small>{job.use_lora ? "LoRA" : "基础模型"} · {dateLabel(job.created_at)}</small></span><em>{LABELS[job.status] || job.status}</em></button>)}</div>
        </div>
      </div>
    </section>
  );
}
