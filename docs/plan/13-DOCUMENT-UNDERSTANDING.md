# 文档理解 V1

## 目标

让 Agent 能安全、按需地理解会话或委托中的 Word、PDF、电子表格和演示文稿，同时避免把整份文档无条件塞入模型上下文。

## 设计原则

- 附件属于 Agent 的会话资产。模型只能用 `attachment_id` 读取当前执行现场明确带入的附件，不能提交任意本机路径。
- Agent 只看到一个稳定工具：`read_document`。
- Word、PDF、Spreadsheet、Presentation 分别是独立内置插件，只负责把格式内容转换成统一的 `DocumentExtraction`。
- 核心基础设施负责解析器选择、权限边界、分页、缓存和数据库升级。
- 解析结果保存在该 Agent 自己的 `brain.db`，以会话、附件、文件哈希、解析器版本共同隔离。
- Desktop 只负责选择和上传文件，不直接解析文档，也不绕过 Agent 读取文件。

## 结构

```text
Desktop / Channel / Assignment
          │ attachment_id
          ▼
    read_document
          │ 当前 ToolExecutionContext 的附件快照
          ▼
    DocumentService ── attachment_derivative cache
          │
          ├─ document_word          DOCX 正文和表格
          ├─ document_pdf           PDF 文本层和页边界
          ├─ document_spreadsheet   XLSX 工作表和公式
          └─ document_presentation  PPTX 幻灯片和备注
```

## V1 行为

- DOCX：正文与表格保持原有顺序，作为 `document` section。
- PPTX：每张幻灯片是一个 section，并带演讲备注。
- PDF：每页是一个 section；纯扫描 PDF 明确返回 `requires_ocr`，本阶段不隐式调用 OCR。
- XLSX：每个工作表是一个 section，保留公式文本；单表最多提取 10000 行、200 列。
- 首次读取返回 section 列表和第一段有限预览；后续通过 `section`、`offset`、`limit` 继续读取。
- 文档内容不再作为普通消息正文持久化，历史消息仍只保存公开附件元数据。

## 暂不包含

- OCR、复杂版面恢复、图表视觉理解。
- DOC、XLS、PPT 等旧二进制 Office 格式。
- 文档编辑和导出；这些继续由现有文件/产物能力处理。
- Desktop 内置解析器或新的 Gateway RPC。
