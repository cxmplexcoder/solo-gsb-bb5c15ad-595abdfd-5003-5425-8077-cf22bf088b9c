import Timeline from './Timeline.jsx'
import { fmtTime, round3 } from '../utils.js'

const ACTION_LABEL = {
  create: { text: '新增', cls: 'ok-text' },
  replace: { text: '更新既有', cls: 'warn-text' },
  keepManual: { text: '保留手工', cls: 'muted' },
  skipDeleted: { text: '已删除·跳过', cls: 'muted' },
  skipOverlap: { text: '与手工校注重叠·跳过', cls: 'muted' },
}

/**
 * Preview of a rule against the project timeline.
 * Props: preview ({matchedSegments, annotations, actions, stats,
 *   overlapsManual}), busy, onApply, onUndo, lastRun
 */
export default function RulePreview({
  preview, busy, onApply, onUndo, lastRun,
}) {
  if (!preview) return null
  const { annotations, matchedSegments, actions, stats, overlapsManual } =
    preview

  // proposal tracks: matched segments dimmed, proposed annotations in purple
  const proposalAnns = annotations.map((a, i) => ({
    ...a,
    id: `preview-${i}`,
    color: '#8e6bc0',
  }))
  const duration = round3(Math.max(
    ...matchedSegments.map((s) => s.end || 0),
    ...annotations.map((a) => a.end || 0), 1))

  return (
    <div className="panel">
      <div className="preview-head">
        <h3>预览（不写入）</h3>
        <div className="stats-grid">
          <span className="stat-box">
            <strong>{stats.matched}</strong><span>命中片段</span>
          </span>
          <span className="stat-box">
            <strong>{stats.proposed}</strong><span>拟生成区间</span>
          </span>
          <span className="stat-box">
            <strong className="ok-text">{stats.create}</strong><span>新增</span>
          </span>
          <span className="stat-box">
            <strong className="warn-text">{stats.replace}</strong><span>更新</span>
          </span>
          <span className="stat-box">
            <strong>{stats.removedStale || 0}</strong><span>移除失效</span>
          </span>
          <span className="stat-box">
            <strong>{(stats.keepManual || 0) + (stats.skipDeleted || 0)
              + (stats.skipOverlap || 0)}</strong>
            <span>保护手工/已删</span>
          </span>
        </div>
      </div>

      <Timeline
        duration={duration}
        segments={matchedSegments}
        annotations={proposalAnns}
        height={56}
      />
      <div className="timeline-hint">
        紫色条为该规则拟生成的区间；下方为命中的转写片段。
      </div>

      <div className="warn-box">
        预览基于项目最近一次保存的文档；编辑器中若有未保存修改，请先在
        编辑器中「保存」，未保存内容不会参与规则应用。
      </div>
      {overlapsManual.length > 0 && (
        <div className="warn-box">
          有 {overlapsManual.length} 个拟生成区间与手工校注时间重叠，
          应用时会跳过这些区间，手工校注不会被覆盖。
        </div>
      )}

      <div className="proposal-list">
        <h4>拟生成的校注（{annotations.length}）</h4>
        {annotations.length === 0 && (
          <div className="empty-hint">当前条件下没有命中片段。</div>
        )}
        {annotations.map((a, i) => {
          const act = ACTION_LABEL[actions[i]?.action] || ACTION_LABEL.create
          return (
            <div className="proposal-row" key={i}>
              <span className={`proposal-action ${act.cls}`}>{act.text}</span>
              <span className="proposal-time">
                {fmtTime(a.start)} – {fmtTime(a.end)}
              </span>
              <span className="proposal-speaker">{a.speaker || '（不限说话人）'}</span>
              <span className="proposal-topic">{a.topic || '（无主题）'}</span>
              <span className="proposal-note muted">{a.note}</span>
            </div>
          )
        })}
      </div>

      <div className="matched-list">
        <h4>命中片段（{matchedSegments.length}）</h4>
        {matchedSegments.map((s) => (
          <div className="matched-row" key={s.id}>
            <span className="proposal-time">{fmtTime(s.start)} – {fmtTime(s.end)}</span>
            <span className="proposal-speaker">{s.speaker}</span>
            <span className="muted">{s.text}</span>
          </div>
        ))}
      </div>

      <div className="preview-actions">
        <button
          className="btn primary"
          disabled={busy || stats.proposed === 0
            || stats.create + stats.replace === 0}
          onClick={onApply}
          title={stats.create + stats.replace === 0
            ? '没有需要新增或更新的区间' : ''}
        >
          确认应用：批量写入 annotations
        </button>
        {lastRun && (
          <button className="btn" disabled={busy} onClick={onUndo}>
            撤销上一次应用（{new Date(lastRun.appliedAt).toLocaleString()}，
            {lastRun.count} 条）
          </button>
        )}
      </div>
    </div>
  )
}
