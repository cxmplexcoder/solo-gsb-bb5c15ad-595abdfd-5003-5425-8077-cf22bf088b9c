import { useEffect, useState } from 'react'

const EMPTY = {
  name: '',
  speaker: '',
  matchMode: 'keyword',
  pattern: '',
  minDuration: 0,
  mergeAdjacent: true,
  mergeGap: 2,
  topic: '',
  noteTemplate: '',
}

/**
 * Create / edit form for one batch rule.
 * Props: initial (rule row or null), speakers, busy, onSave(config), onCancel
 */
export default function RuleForm({ initial, speakers, busy, onSave, onCancel }) {
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState('')

  useEffect(() => {
    setForm(initial ? { ...EMPTY, ...initial.config } : EMPTY)
    setError('')
  }, [initial])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submit = () => {
    const config = {
      ...form,
      name: form.name.trim(),
      speaker: form.speaker.trim(),
      pattern: form.pattern,
      topic: form.topic.trim(),
      noteTemplate: form.noteTemplate,
      minDuration: Number(form.minDuration) || 0,
      mergeGap: Number(form.mergeGap) || 0,
    }
    if (!config.name) {
      setError('请填写规则名称')
      return
    }
    if (!Number.isFinite(config.minDuration) || config.minDuration < 0) {
      setError('最短持续时间必须是非负数字')
      return
    }
    if (!Number.isFinite(config.mergeGap) || config.mergeGap < 0) {
      setError('合并间隔必须是非负数字')
      return
    }
    if (config.matchMode === 'regex' && config.pattern) {
      try {
        new RegExp(config.pattern)
      } catch (e) {
        setError(`正则表达式无效：${e.message}`)
        return
      }
    }
    onSave(config)
  }

  return (
    <div className="rule-form panel">
      <h3>{initial ? `编辑规则：${initial.config.name}` : '新建规则'}</h3>
      <div className="rule-form-grid">
        <label>
          规则名称 <span className="req">*</span>
          <input
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="例如：改制相关发言"
          />
        </label>
        <label>
          说话人（留空 = 不限）
          <input
            list="rule-speaker-list"
            value={form.speaker}
            onChange={(e) => set('speaker', e.target.value)}
            placeholder="例如：受访者"
          />
          <datalist id="rule-speaker-list">
            {speakers.map((s) => <option key={s} value={s} />)}
          </datalist>
        </label>
        <label>
          匹配方式
          <select
            value={form.matchMode}
            onChange={(e) => set('matchMode', e.target.value)}
          >
            <option value="keyword">关键词（包含）</option>
            <option value="regex">正则表达式</option>
          </select>
        </label>
        <label>
          {form.matchMode === 'keyword' ? '关键词' : '正则表达式'}
          （留空 = 仅按说话人 / 时长）
          <input
            value={form.pattern}
            onChange={(e) => set('pattern', e.target.value)}
            placeholder={form.matchMode === 'keyword' ? '改制' : '改[制置]'}
          />
        </label>
        <label>
          最短持续时间（秒）
          <input
            type="number" min="0" step="0.1"
            value={form.minDuration}
            onChange={(e) => set('minDuration', e.target.value)}
          />
        </label>
        <label>
          相邻命中合并
          <select
            value={form.mergeAdjacent ? 'yes' : 'no'}
            onChange={(e) => set('mergeAdjacent', e.target.value === 'yes')}
          >
            <option value="yes">合并为一个区间</option>
            <option value="no">每个片段各生成一条</option>
          </select>
        </label>
        <label>
          合并最大间隔（秒）
          <input
            type="number" min="0" step="0.1"
            value={form.mergeGap}
            disabled={!form.mergeAdjacent}
            onChange={(e) => set('mergeGap', e.target.value)}
          />
        </label>
        <label>
          生成校注的主题
          <input
            value={form.topic}
            onChange={(e) => set('topic', e.target.value)}
            placeholder="留空则不填主题"
          />
        </label>
        <label className="wide">
          备注模板（可用变量：
          <code>{'{{rule}} {{text}} {{speaker}} {{start}} {{end}} {{matched}}'}</code>）
          <textarea
            rows={2}
            value={form.noteTemplate}
            onChange={(e) => set('noteTemplate', e.target.value)}
            placeholder="例如：{{rule}} 命中 {{matched}} 段：{{text}}"
          />
        </label>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="rule-form-actions">
        <button className="btn primary" disabled={busy} onClick={submit}>
          {initial ? '保存修改' : '创建规则'}
        </button>
        <button className="btn" onClick={onCancel} disabled={busy}>
          取消
        </button>
      </div>
    </div>
  )
}
