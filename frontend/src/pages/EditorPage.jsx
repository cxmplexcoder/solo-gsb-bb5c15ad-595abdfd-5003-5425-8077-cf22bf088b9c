import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api.js'
import Timeline from '../components/Timeline.jsx'
import SegmentList from '../components/SegmentList.jsx'
import AnnotationModal from '../components/AnnotationModal.jsx'
import {
  clone, downloadJson, emptyDocument, makeAnnotation, makeSegment, round3,
} from '../utils.js'

export default function EditorPage() {
  const { id } = useParams()
  const [project, setProject] = useState(null)
  const [doc, setDoc] = useState(emptyDocument())
  const [name, setName] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [modal, setModal] = useState(null) // { initial }
  const importRef = useRef(null)

  useEffect(() => {
    api.getProject(id).then((p) => {
      setProject(p)
      setDoc(p.document || emptyDocument())
      setName(p.name)
    }).catch((e) => setError(e.message))
  }, [id])

  const update = (patch) => {
    setDoc((d) => ({ ...d, ...patch }))
    setDirty(true)
  }

  const save = useCallback(async () => {
    setSaving(true); setError('')
    try {
      const p = await api.saveProject(id, { name: name.trim(), document: doc })
      setProject(p)
      setDirty(false)
      setMessage('已保存 ' + new Date().toLocaleTimeString())
      setTimeout(() => setMessage(''), 2500)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }, [id, name, doc])

  useEffect(() => {
    const h = (e) => {
      if (dirty) { e.preventDefault(); e.returnValue = '' }
    }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  const speakers = useMemo(() => {
    const set = new Set()
    doc.segments.forEach((s) => s.speaker && set.add(s.speaker))
    doc.annotations.forEach((a) => a.speaker && set.add(a.speaker))
    return [...set]
  }, [doc])

  const duration = useMemo(() => {
    const ends = [...doc.segments, ...doc.annotations].map((x) => x.end || 0)
    return round3(Math.max(0, ...ends))
  }, [doc])

  const onTimelineSelect = (range) => setModal({ initial: range })

  const saveAnnotation = (ann) => {
    const exists = doc.annotations.some((a) => a.id === ann.id)
    const next = exists
      ? doc.annotations.map((a) => (a.id === ann.id ? ann : a))
      : [
          ...doc.annotations,
          { ...makeAnnotation(ann.start, ann.end, ann.speaker,
              ann.topic, ann.note), color: ann.color },
        ]
    update({ annotations: next })
    setModal(null)
  }

  const deleteAnnotation = (annId) => {
    update({
      annotations: doc.annotations.filter((a) => a.id !== annId),
    })
    setModal(null)
  }

  const addSegment = () => {
    const last = doc.segments[doc.segments.length - 1]
    const start = last ? last.end : 0
    update({
      segments: [...doc.segments,
        makeSegment(start, round3(start + 1), '', '新片段')],
    })
  }

  const onImportFile = async (file) => {
    if (!window.confirm(
      '导入将替换全部转写片段（已有校注会保留）。确定继续？')) {
      importRef.current.value = ''
      return
    }
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const p = await api.importIntoProject(id, fd)
      setDoc(p.document)
      setProject(p)
      setDirty(true)
    } catch (e) {
      setError(`导入失败：${e.message}`)
    } finally {
      importRef.current.value = ''
    }
  }

  /** Offline workflow: export the current saved doc as a working copy. */
  const exportCopy = (side) => {
    const payload = {
      _offlineCopy: true,
      baseProjectId: id,
      baseProjectName: project?.name || '',
      exportedAt: new Date().toISOString(),
      editor: side,
      document: doc,
    }
    downloadJson(
      `${project?.name || 'project'}-${side}-copy.json`, payload)
  }

  if (!project && !error) return <div className="page">加载中…</div>

  return (
    <div className="page editor">
      <div className="page-head">
        <div className="title-line">
          <Link to="/" className="back">← 项目</Link>
          <input
            className="project-name"
            value={name}
            onChange={(e) => { setName(e.target.value); setDirty(true) }}
          />
          {dirty && <span className="badge warn">未保存</span>}
        </div>
        <div className="head-actions">
          <button className="btn" onClick={() => importRef.current?.click()}>
            导入转写
          </button>
          <input
            ref={importRef} type="file" hidden
            accept=".json,.txt,.srt,.vtt"
            onChange={(e) => e.target.files?.[0] && onImportFile(e.target.files[0])}
          />
          <button className="btn" onClick={() => exportCopy('A')}>
            导出 A 离线副本
          </button>
          <button className="btn" onClick={() => exportCopy('B')}>
            导出 B 离线副本
          </button>
          <Link className="btn" to="/merge">前往三方合并 →</Link>
          <button className="btn primary" disabled={saving || !dirty} onClick={save}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {message && <div className="ok">{message}</div>}

      <div className="panel">
        <Timeline
          duration={duration}
          segments={doc.segments}
          annotations={doc.annotations}
          selectedId={modal?.initial?.id}
          onSelect={onTimelineSelect}
          onClickItem={(annId) => {
            const a = doc.annotations.find((x) => x.id === annId)
            if (a) setModal({ initial: clone(a) })
          }}
        />
      </div>

      <SegmentList
        segments={doc.segments}
        onChange={(segments) => update({ segments })}
        onDelete={(sid) => update({
          segments: doc.segments.filter((s) => s.id !== sid),
        })}
        onAdd={addSegment}
      />

      <AnnotationList
        annotations={doc.annotations}
        onClick={(a) => setModal({ initial: clone(a) })}
        onDelete={deleteAnnotation}
      />

      {modal && (
        <AnnotationModal
          initial={modal.initial}
          speakers={speakers}
          onSave={saveAnnotation}
          onClose={() => setModal(null)}
          onDelete={deleteAnnotation}
        />
      )}
    </div>
  )
}

function AnnotationList({ annotations, onClick, onDelete }) {
  return (
    <div className="annotation-list">
      <h3>校注（{annotations.length}）</h3>
      {annotations.length === 0 && (
        <div className="empty-hint">
          在上方时间轴拖选区间即可添加带说话人、主题、备注的校注。
        </div>
      )}
      <div className="ann-grid">
        {annotations.map((a) => (
          <div
            key={a.id}
            className="ann-chip"
            style={{ borderLeftColor: a.color || '#5b8def' }}
            onClick={() => onClick(a)}
          >
            <div className="ann-chip-head">
              <strong>{a.topic || '（未命名主题）'}</strong>
              <button
                className="btn icon danger"
                onClick={(e) => { e.stopPropagation(); onDelete(a.id) }}
              >
                ✕
              </button>
            </div>
            <div className="muted small">
              {a.start.toFixed(2)}s – {a.end.toFixed(2)}s
              {a.speaker ? ` · ${a.speaker}` : ''}
            </div>
            {a.note && <div className="ann-note">{a.note}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
