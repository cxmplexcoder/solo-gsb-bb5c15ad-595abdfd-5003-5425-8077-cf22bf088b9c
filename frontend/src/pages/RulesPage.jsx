import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api.js'
import RuleForm from '../components/RuleForm.jsx'
import RulePreview from '../components/RulePreview.jsx'

export default function RulesPage() {
  const { id } = useParams()
  const [project, setProject] = useState(null)
  const [rules, setRules] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [editing, setEditing] = useState(null) // rule row being edited
  const [creating, setCreating] = useState(false)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const refresh = useCallback(async (keepSelection = true) => {
    const p = await api.getProject(id)
    setProject(p)
    const rs = await api.listRules(id)
    setRules(rs)
    if (keepSelection) {
      const sel = rs.find((r) => r.id === selectedId)
      if (!sel) {
        setSelectedId(null)
        setPreview(null)
      }
    }
    return { p, rs }
  }, [id, selectedId])

  useEffect(() => { refresh(false).catch((e) => setError(e.message)) }, [id])

  const selected = useMemo(
    () => rules.find((r) => r.id === selectedId) || null,
    [rules, selectedId])

  const rerenderPreview = useCallback(async (rid) => {
    const pv = await api.previewRule(id, rid)
    setPreview(pv)
  }, [id])

  const speakers = useMemo(() => {
    const set = new Set()
    ;(project?.document?.segments || []).forEach(
      (s) => s.speaker && set.add(s.speaker))
    return [...set]
  }, [project])

  const flash = (msg) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

  const selectRule = (rid) => {
    setSelectedId(rid)
    setCreating(false)
    setEditing(null)
    setPreview(null)
    setError('')
  }

  const saveRule = async (config) => {
    setBusy(true); setError('')
    try {
      let saved
      if (editing) {
        saved = await api.updateRule(id, editing.id, config)
      } else {
        saved = await api.createRule(id, config)
      }
      await refresh(false)
      setSelectedId(saved.id)
      setEditing(null); setCreating(false); setPreview(null)
      flash(editing ? '规则已保存' : '规则已创建，可点击「预览」查看命中')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const removeRule = async (rule) => {
    if (!window.confirm(
      `删除规则「${rule.config.name}」？\n该规则已生成的校注不会被删除，仅删除规则本身。`)) {
      return
    }
    setBusy(true); setError('')
    try {
      await api.deleteRule(id, rule.id)
      if (selectedId === rule.id) {
        setSelectedId(null); setPreview(null)
      }
      await refresh(false)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const runPreview = async () => {
    if (!selected) return
    setBusy(true); setError('')
    try {
      const pv = await api.previewRule(id, selected.id)
      setPreview(pv)
    } catch (e) {
      setError(`预览失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!selected || !preview) return
    const s = preview.stats
    const msg = s.replace > 0
      ? `将新增 ${s.create} 条、更新 ${s.replace} 条校注` +
        `${s.removedStale ? `、移除 ${s.removedStale} 条失效区间` : ''}。\n` +
        '手工标注与手工修改过的规则产物不会被覆盖。确定写入？'
      : `将新增 ${s.create} 条校注。\n手工标注不会被覆盖。确定写入？`
    if (!window.confirm(msg)) return
    setBusy(true); setError('')
    try {
      const res = await api.applyRule(id, selected.id)
      const { rs } = await refresh(false)
      setSelectedId(selected.id)
      flash(`已写入 ${res.generated.length} 条校注，可「撤销上一次应用」`)
      const fresh = rs.find((r) => r.id === selected.id)
      if (fresh) await rerenderPreview(fresh.id)
    } catch (e) {
      setError(`应用失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const undo = async () => {
    const last = selected?.lastRun
    if (!last) return
    if (!window.confirm(
      `撤销该规则上一次应用（${last.count} 条）？\n` +
      '之后手工修改过的校注会保留为手工标注；若上一次应用替换过更早的结果，将一并恢复。')) {
      return
    }
    setBusy(true); setError('')
    try {
      const res = await api.undoRun(id, last.id)
      const { rs } = await refresh(false)
      flash(`已撤销：移除 ${res.removed} 条，恢复 ${res.restored} 条` +
        `${res.detached ? `，${res.detached} 条手工修改已保留` : ''}`)
      const fresh = rs.find((r) => r.id === selected.id)
      if (fresh) await rerenderPreview(fresh.id)
    } catch (e) {
      setError(`撤销失败：${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  if (!project && !error) return <div className="page">加载中…</div>

  return (
    <div className="page rules-page">
      <div className="page-head">
        <div className="title-line">
          <Link to={`/projects/${id}`} className="back">← 返回编辑器</Link>
          <h2>规则批量标注 · {project?.name}</h2>
        </div>
        <div className="head-actions">
          <Link className="btn" to={`/projects/${id}`}>在时间轴查看结果</Link>
          <a className="btn" href={api.exportUrl(id)}>导出 JSON</a>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {message && <div className="ok">{message}</div>}

      <div className="rules-layout">
        <div className="rules-side panel">
          <div className="rules-side-head">
            <h3>规则（{rules.length}）</h3>
            <button
              className="btn small primary"
              disabled={busy}
              onClick={() => { setCreating(true); setEditing(null); setSelectedId(null) }}
            >
              + 新建规则
            </button>
          </div>
          {rules.map((r) => (
            <div
              key={r.id}
              className={`rule-item ${selectedId === r.id ? 'active' : ''}`}
              onClick={() => selectRule(r.id)}
            >
              <div className="rule-item-name">{r.config.name}</div>
              <div className="rule-item-meta muted small">
                {r.config.speaker || '不限说话人'} ·{' '}
                {r.config.matchMode === 'regex' ? '正则' : '关键词'}
                {r.config.pattern ? `「${r.config.pattern}」` : '（无文本条件）'}
                {r.config.minDuration ? ` · ≥${r.config.minDuration}s` : ''}
              </div>
              {r.lastRun && (
                <div className="rule-item-run muted small">
                  上次应用：{new Date(r.lastRun.appliedAt).toLocaleString()} ·
                  {' '}{r.lastRun.count} 条
                </div>
              )}
            </div>
          ))}
          {rules.length === 0 && !creating && (
            <div className="empty-hint">还没有规则，点击「新建规则」开始批量标注。</div>
          )}
        </div>

        <div className="rules-main">
          {creating && (
            <RuleForm
              initial={null}
              speakers={speakers}
              busy={busy}
              onSave={saveRule}
              onCancel={() => setCreating(false)}
            />
          )}
          {editing && (
            <RuleForm
              initial={editing}
              speakers={speakers}
              busy={busy}
              onSave={saveRule}
              onCancel={() => setEditing(null)}
            />
          )}

          {selected && !editing && (
            <div className="panel rule-detail">
              <h3>{selected.config.name}</h3>
              <dl className="rule-spec">
                <dt>说话人</dt><dd>{selected.config.speaker || '不限'}</dd>
                <dt>文本条件</dt>
                <dd>
                  {selected.config.pattern
                    ? `${selected.config.matchMode === 'regex' ? '正则' : '关键词'}：${selected.config.pattern}`
                    : '无（仅按说话人 / 时长）'}
                </dd>
                <dt>最短持续</dt>
                <dd>{selected.config.minDuration} 秒</dd>
                <dt>相邻合并</dt>
                <dd>
                  {selected.config.mergeAdjacent
                    ? `间隔 ≤ ${selected.config.mergeGap} 秒的相邻命中合并`
                    : '不合并，逐片段生成'}
                </dd>
                <dt>主题</dt><dd>{selected.config.topic || '（空）'}</dd>
                <dt>备注模板</dt>
                <dd className="mono">{selected.config.noteTemplate || '（空）'}</dd>
              </dl>
              <div className="rule-detail-actions">
                <button className="btn primary" disabled={busy} onClick={runPreview}>
                  预览命中
                </button>
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => { setEditing(selected); setCreating(false) }}
                >
                  编辑规则
                </button>
                <button className="btn danger" disabled={busy}
                  onClick={() => removeRule(selected)}>
                  删除规则
                </button>
              </div>
            </div>
          )}

          {selected && preview && !editing && (
            <RulePreview
              preview={preview}
              busy={busy}
              lastRun={selected.lastRun}
              onApply={apply}
              onUndo={undo}
            />
          )}

          {!selected && !creating && (
            <div className="panel empty-hint">
              选择左侧规则查看详情，或新建一条规则。<br />
              规则会按「说话人 + 关键词/正则 + 最短持续时间」命中转写片段，
              在时间轴预览后批量生成校注；重复运行只更新该规则自己的结果，
              手工标注始终保留，且可撤销每一次应用。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
