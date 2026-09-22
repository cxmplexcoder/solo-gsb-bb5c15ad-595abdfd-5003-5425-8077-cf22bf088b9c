# 访谈音频校注 Web 应用

面向口述史 / 访谈录音的**转写片段校注**工具：导入带时间戳的转写稿，在时间轴上
拖选区间，为区间标注**说话人、主题、备注**，导出校注 JSON。支持两位校注者离线
各自编辑同一份基准稿后，进行**三方合并（three-way merge）**——互不重叠的改动
自动合并，重叠改动保留双方版本并要求逐项裁决，裁决结果可继续导出或写回项目。

- 前端：React 18 + Vite（纯 CSS，无 UI 框架依赖）
- 后端：FastAPI（Python 3.11）
- 数据库：本地 SQLite（单文件，挂载于 `./data`）
- 部署：单镜像、单容器，Docker 一键启动

---

## 一键启动

### 方式一：Docker Compose（推荐）

```bash
docker compose up -d --build
```

启动后访问：

> **http://localhost:8000**

停止：

```bash
docker compose down
```

### 方式二：Docker 原生命令

```bash
docker build -t interview-annotator .
docker run -d --name interview-annotator \
  -p 8000:8000 \
  -v "$PWD/data:/data" \
  interview-annotator
```

访问 **http://localhost:8000**。

SQLite 数据库文件位于容器内 `/data/annotation.db`，通过宿主机 `./data`
目录持久化，删除容器不丢数据。更换端口可改 `-p` 映射（容器内固定监听 8000）。

健康检查：`GET http://localhost:8000/api/health`。

---

## 使用流程

### 1. 导入转写稿

在首页点击「导入转写稿新建…」，或在项目内点击「导入转写」（项目内导入会替换
片段但**保留已有校注**）。支持三种格式：

**带时间戳的纯文本**（`.txt` / `.srt` / `.vtt` 后缀，或内容无法解析为 JSON 时）：

```text
[00:00:00] 访谈者: 感谢您今天接受访谈
[00:00:19] 受访者: 我叫李明，在制造厂工作了二十多年
[00:00:34] --> [00:00:40] 受访者: 后来 2003 年改制
[01:09.5] 受访者: 最早全靠手摇车床
```

支持 `hh:mm:ss`、`mm:ss`、`mm:ss.mmm` 等时间格式；说话人通过行内的
`名字: 文本`（中英文冒号均可）识别；省略结束时间时，默认持续到下一片段开始
（最后一片段默认 1 秒）。

**JSON 片段数组**：

```json
[
  {"id": "seg-001", "start": 0.0, "end": 4.2,
   "speaker": "访谈者", "text": "感谢您今天接受访谈"}
]
```

未提供 `id` 时后端自动生成；也接受 `startTime/endTime/begin/stop/content`
等别名字段。

**此前导出的校注 JSON**（含 `segments` 与 `annotations`），直接还原整个项目。

示例文件见 [`examples/`](examples/)。

### 2. 时间轴校注

- 顶部时间轴显示片段（灰）与校注（彩色条）；
- **在时间轴上按住鼠标拖选区间**，弹窗中填写说话人、主题、备注；
- 点击已有校注条可再次编辑 / 删除；
- 片段的说话人与文本可直接在下方表格修改、新增或删除；
- 「保存」写入 SQLite；可随时「导出 JSON」下载完整校注文档。

### 3. 双人离线编辑与三方合并（核心）

1. 在基准项目中分别点击「导出 A 离线副本」「导出 B 离线副本」，得到两份 JSON；
   （也可以直接复制项目给两位校注者，只要改动基于同一份基准。）
2. 两人各自在**新建项目时导入自己的离线副本 JSON**，独立完成校注并保存；
   或直接编辑副本文件中的 `document`。
3. 打开顶部「**三方合并**」页：
   - 基准（Base）：下拉选择原始项目，或选择基准 JSON；
   - A、B：分别选择两人的离线副本文件；
   - 点击「开始三方合并」。
4. 页面展示：
   - **自动合并的互不重叠改动**（新增 / 修改 / 删除），按片段与校注分别统计；
   - **需要逐项裁决的冲突**，每张卡片并排显示基准、A、B 三个版本。
5. 裁决方式（可混合使用）：
   - 整条采用 A / 采用 B / 丢弃；
   - 区间重叠冲突还可「双方都保留」；
   - 「按字段逐项裁决」：仅对双方改得不一致的字段选 A 或 B，其余字段自动并入；
   - 「自定义合并值 ✏️」：手工编辑合并后的最终内容。
6. 全部裁决后：
   - 「导出裁决结果 JSON」下载合并文档；
   - 「另存为新项目」；
   - 若基准来自下拉选择的项目，可「写回基准项目」。

> 未裁决完的冲突条目不会进入合并文档（页面会明确提示），裁决可反复调整、
> 实时预览，且不会改动原始项目，直到选择写回 / 另存。

---

## 合并规则说明

合并以条目的稳定 `id`（片段 `seg-*`、校注 `ann-*`）在 **基准 / A / B**
三份文档中比对：

| 情形 | 结果 |
| --- | --- |
| 只有一方新增、修改、删除 | 自动采用 |
| 双方修改同一 id 且内容相同 | 自动采用 |
| 双方修改同一 id，但改动落在**不同字段** | 字段级自动合并 |
| 双方修改同一 id，且同一字段改成不同值 | **字段冲突**，逐项裁决 |
| 一方修改、另一方删除同一条 | **修改/删除冲突**，逐项裁决 |
| 双方各自新增校注，且时间区间互不重叠 | 自动并存（端点相接不算重叠） |
| 双方各自新增校注，且时间区间重叠 | **区间重叠冲突**（重叠链聚合成一个冲突组），逐项裁决 |
| 双方都删除同一条 | 自动删除 |

自定义合并值在服务端校验：时间必须为非负数字、`end >= start`、片段文本非空。

导出 / 合并的 JSON 结构：

```json
{
  "segments": [
    {"id": "seg-…", "start": 0.0, "end": 4.2,
     "speaker": "访谈者", "text": "…"}
  ],
  "annotations": [
    {"id": "ann-…", "start": 0.0, "end": 18.5,
     "speaker": "受访者", "topic": "个人背景", "note": "…"}
  ]
}
```

离线副本文件在文档之外附带 `baseProjectId / editor / exportedAt` 元数据，
合并页能直接识别其 `document`。

---

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 新建项目 |
| GET/PUT/DELETE | `/api/projects/{id}` | 读取 / 保存文档 / 删除 |
| GET | `/api/projects/{id}/export` | 下载校注 JSON |
| POST | `/api/import` | 上传文件（multipart）或 JSON 文本解析转写稿 |
| POST | `/api/projects/{id}/import` | 导入到指定项目（保留校注） |
| POST | `/api/merge` | 三方合并，可携带 `resolutions` 裁决 |
| GET | `/api/health` | 健康检查 |

`POST /api/merge` 请求体：

```json
{
  "base": { "segments": [], "annotations": [] },
  "a": { "…": "…" },
  "b": { "…": "…" },
  "resolutions": {
    "segments:seg-001:modify": {"choice": "fields", "fields": {"speaker": "a"}},
    "annotations:interval:0:ann-a": {"choice": "keep"}
  },
  "saveAsProject": "合并结果"
}
```

`choice` 取值：`a` / `b` / `custom`（附 `value`）/ `drop` / `keep`
（区间冲突）/ `fields`（附字段选择）。`base` 也可省略而改用
`projectId` 指定基准项目；全部冲突裁决完毕时结果自动写回该项目。

交互式文档（Swagger）：http://localhost:8000/docs

---

## 本地开发（不用 Docker）

后端：

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./dev-data STATIC_DIR=nonexistent \
  uvicorn app.main:app --reload --port 8000
```

前端（开发服务器，自动代理 `/api` 到 8000）：

```bash
cd frontend
npm install
npm run dev
```

访问 Vite 输出的地址（默认 **http://localhost:5173**）。

运行后端测试：

```bash
cd backend
python -m pytest test_merge.py -q
```

测试覆盖：互不重叠改动自动合并、同字段/不同字段冲突、字段级裁决、
修改/删除冲突、区间重叠与重叠链聚类、端点相接不冲突、自定义值校验、
增删混合与时间排序等 14 个用例。

---

## 目录结构

```
.
├── Dockerfile               # 多阶段构建：Vite 构建 → FastAPI 托管静态文件
├── docker-compose.yml       # 一键启动，端口 8000，数据卷 ./data
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 路由
│   │   ├── merge.py         # 三方合并算法（analyze / build_merged）
│   │   ├── importer.py      # 转写稿解析（纯文本 / JSON）
│   │   ├── db.py            # SQLite 持久化
│   │   └── schemas.py       # Pydantic 模型
│   ├── test_merge.py        # 合并算法测试
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/           # 项目列表 / 编辑器 / 三方合并
│   │   ├── components/      # 时间轴、标注弹窗、片段表、冲突裁决卡
│   │   ├── api.js  utils.js  styles.css
│   └── vite.config.js
└── examples/                # 示例转写稿
```
