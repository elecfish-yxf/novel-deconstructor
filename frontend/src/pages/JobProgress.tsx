import { useEffect, useMemo, useState } from "react";
import { api, Job, JobLog } from "../api";
import StatusPill from "../components/StatusPill";

export default function JobProgress({
  jobId,
  onJobChange,
  onViewResults,
}: {
  jobId: string;
  onJobChange: (job: Job) => void;
  onViewResults: () => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [logs, setLogs] = useState<JobLog[]>([]);
  const [runtimeApiKey, setRuntimeApiKey] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const [nextJob, nextLogs] = await Promise.all([api.getJob(jobId), api.getLogs(jobId)]);
    setJob(nextJob);
    setLogs(nextLogs);
    onJobChange(nextJob);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    const timer = window.setInterval(() => {
      load().catch((err) => setError(err.message));
    }, 1800);
    return () => window.clearInterval(timer);
  }, [jobId]);

  const progress = useMemo(() => {
    if (!job || !job.total_chunks) return 0;
    return Math.round((job.completed_chunks / job.total_chunks) * 100);
  }, [job]);

  async function action(fn: (id: string) => Promise<Job>) {
    setError("");
    try {
      const next = await fn(jobId);
      setJob(next);
      onJobChange(next);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function runtimeAction(fn: (id: string, payload: { api_key?: string }) => Promise<Job>) {
    setError("");
    if (job && !job.dry_run && !runtimeApiKey.trim()) {
      setError("继续或重试非 dry-run 任务前，请重新填写你自己的 API Key。");
      return;
    }
    try {
      const next = await fn(jobId, { api_key: runtimeApiKey.trim() || undefined });
      setJob(next);
      onJobChange(next);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  if (!job) {
    return (
      <section>
        <h1>任务进度</h1>
        {error ? <div className="alert">{error}</div> : <p>正在读取任务...</p>}
      </section>
    );
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">{job.id}</p>
          <h1>任务进度</h1>
        </div>
        <StatusPill status={job.status} />
      </div>
      {error && <div className="alert">{error}</div>}

      <div className="metric-strip">
        <div>
          <span>总任务项</span>
          <strong>{job.total_chunks}</strong>
        </div>
        <div>
          <span>已完成</span>
          <strong>{job.completed_chunks}</strong>
        </div>
        <div>
          <span>失败</span>
          <strong>{job.failed_chunks}</strong>
        </div>
        <div>
          <span>当前章节</span>
          <strong>{job.current_chunk_title || "无"}</strong>
        </div>
      </div>

      <div className="panel">
        <div className="progress-row">
          <div className="progress-bar">
            <span style={{ width: `${progress}%` }} />
          </div>
          <strong>{progress}%</strong>
        </div>
        <div className="button-row">
          <button onClick={() => action(api.pauseJob)} disabled={job.status !== "running"}>
            暂停
          </button>
          <button onClick={() => runtimeAction(api.resumeJob)} disabled={!["paused", "failed"].includes(job.status)}>
            继续
          </button>
          <button onClick={() => action(api.cancelJob)} disabled={["completed", "cancelled"].includes(job.status)}>
            取消
          </button>
          <button onClick={() => runtimeAction(api.retryFailed)} disabled={job.failed_chunks === 0}>
            重试失败
          </button>
          <button className="primary" onClick={onViewResults}>
            查看结果
          </button>
        </div>
        {!job.dry_run && ["paused", "failed"].includes(job.status) && (
          <div className="runtime-key-row">
            <label>
              继续/重试用 API Key
              <input
                type="password"
                value={runtimeApiKey}
                onChange={(event) => setRuntimeApiKey(event.target.value)}
                placeholder="后台不会保存 API Key，继续任务时请重新填写"
              />
            </label>
          </div>
        )}
      </div>

      <div className="log-panel">
        {logs.map((log) => (
          <div key={log.id} className={`log-line level-${log.level}`}>
            <time>{new Date(log.created_at).toLocaleTimeString()}</time>
            <span>{log.message}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
