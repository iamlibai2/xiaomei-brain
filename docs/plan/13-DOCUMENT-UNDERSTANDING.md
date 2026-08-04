# 文档理解：现状与后续设计

## 文档状态

- V1 已实现并可用。
- V2 仅作为后续设计保存，当前不启动开发。
- 后续应由真实企业业务场景暴露的问题驱动实现，避免为了抽象完整而重做现有能力。

## 目标

让 Agent 安全、按需地读取会话或委托中的 Word、PDF、电子表格和演示文稿，同时避免把整份文档无条件塞入模型上下文。

长期目标不是“支持打开更多文件”，而是让 Agent 能够：

- 理解文档的业务结构，而不只是读取纯文本；
- 在大文档中准确找到相关内容；
- 对表格、图表、页面和批注进行结构化分析；
- 在回答中给出稳定、可核验的来源位置；
- 联合分析多份文档；
- 在扫描件没有文本层时按需使用 OCR。

## 已确认的设计决策

1. 不重新建设文档读取基础设施。现有 `DocumentService`、`DocumentExtraction`、格式插件和 `read_document` 是后续演进基础。
2. Desktop 只负责选择、上传和展示文件，不直接解析业务内容，也不能绕过 Agent 读取文件。
3. Agent 只能通过当前执行现场授权的 `attachment_id` 读取附件，不能向工具提交任意本机路径。
4. 格式差异由插件处理；Agent 面向稳定、少量的通用文档工具。
5. 文档内容按需读取，不能把整份大文档作为普通聊天正文持久化或一次性注入上下文。
6. 后续扩展重点是“结构、检索、来源和 OCR”，不是增加另一套文档管理页面。
7. 当前暂缓 V2。先用真实合同、报价、报表、标书等任务验证 V1，再针对实际缺口实施。

## V1 当前实现

### 运行链路

```text
Desktop / Channel / Assignment
          │
          │ attachment_id
          ▼
    ToolExecutionContext
          │ 当前执行现场授权的附件快照
          ▼
      read_document
          ▼
     DocumentService
       ├─ 根据文件名和 MIME 选择 Extractor
       ├─ 计算文件 SHA-256
       ├─ 查询或写入 brain.db 解析缓存
       └─ 按 section / offset / limit 返回有限内容
          │
          ├─ document_word
          ├─ document_pdf
          ├─ document_spreadsheet
          └─ document_presentation
```

### 统一数据结构

```python
DocumentExtraction
├─ extractor_id
├─ extractor_version
├─ metadata
└─ sections: tuple[DocumentSection, ...]

DocumentSection
├─ key
├─ title
├─ content
└─ metadata
```

### 格式支持

| 格式 | 当前提取方式 | 当前边界 |
|---|---|---|
| DOCX | 按正文顺序提取段落和表格，合并为 `document` section | 表格被转换为制表符文本；标题级别、批注、图片及精确位置保留不足 |
| XLSX | 每个工作表一个 section，读取公式文本 | 内容被展平为行文本；缺少稳定单元格坐标、合并区域、格式和图表语义 |
| PPTX | 每页一个 section，读取页面文字和演讲者备注 | 缺少形状层次、坐标、图片、图表和视觉关系 |
| PDF | 每页一个 section，读取文本层 | 扫描件只标记 `requires_ocr`；缺少坐标、表格结构和复杂版面恢复 |

### 已有能力

- 首次读取返回 section 列表和第一段有限预览。
- 后续使用 `section`、`offset`、`limit` 继续读取。
- 单次返回最多 20,000 字符。
- 解析缓存按会话、附件、文件哈希、解析器和解析器版本隔离。
- Agent 产物在同一轮被修改后，`read_document` 可以读取最新受管文件，而不是旧的附件快照。
- Desktop 与 Gateway 不承担文档语义解析。

## V1 的真实能力边界

V1 已能完成普通阅读、摘要和基础数据分析，但本质上仍以“分段文本读取”为主。

目前容易出现的问题：

- 模型知道一段内容来自某个工作表或页面，但无法稳定引用到具体单元格、表格或段落。
- Word 和 Excel 表格被展平后，复杂表头、合并单元格和层级关系可能丢失。
- PPT 中“文字与哪张图、哪个区域对应”无法表达。
- PDF 双栏、复杂表格、浮动文本框的阅读顺序可能不可靠。
- 扫描 PDF 和图片型文档无法直接读取。
- 大文档需要模型逐段调用 `read_document`，缺少文档内搜索工具。
- 多文件联合分析主要依赖模型分别读取，不具备统一的来源索引。

## V2 总体方案

V2 在现有 `DocumentExtraction` 上增加结构化 Block 和稳定来源位置，不另建平行解析系统。

### 目标数据模型

```text
DocumentExtraction
├─ metadata
├─ sections
│  └─ DocumentSection
│     ├─ key / title
│     ├─ content                 兼容现有有限文本读取
│     └─ blocks
│        ├─ heading
│        ├─ paragraph
│        ├─ table
│        ├─ image
│        ├─ chart
│        ├─ note
│        └─ annotation
└─ source index
```

建议新增：

```python
DocumentBlock
├─ block_id: str
├─ block_type: str
├─ text: str
├─ location: SourceLocation
├─ data: dict
└─ metadata: dict

SourceLocation
├─ section_key: str
├─ page: int | None
├─ slide: int | None
├─ sheet: str | None
├─ cell_range: str | None
├─ paragraph: int | None
├─ table: int | None
└─ bounding_box: tuple | None
```

示例：

```json
{
  "block_id": "sheet-sales-table-2",
  "block_type": "table",
  "text": "华东地区销售额……",
  "location": {
    "section_key": "sheet:1",
    "sheet": "销售明细",
    "cell_range": "A4:F28"
  },
  "data": {
    "rows": []
  }
}
```

### 工具设计

保留现有 `read_document`，不让 Agent 直接面对各格式专用工具。

后续可增加：

#### `search_document`

- 输入：`attachment_id`、查询文本、可选 section、返回数量。
- 在已解析 Block 中查找内容。
- 返回相关片段、Block 类型和来源位置。
- 第一版可使用关键词与结构索引；需要语义搜索时再接入现有向量服务。

#### `extract_table`

- 输入：`attachment_id`、`block_id`，或明确的 sheet/range。
- 返回二维数组、表头、来源范围和必要格式信息。
- 避免模型从制表符文本反推复杂表格结构。

#### `read_document`

继续承担：

- 查看文档概览；
- 查看 section 列表；
- 有限分页阅读；
- 根据 `block_id` 获取一个结构块的详细内容。

暂不增加面向用户的格式专用工具，例如 `read_word`、`read_excel`、`read_pdf`。

## 格式解析增强

### Word

- 保留标题级别和段落序号。
- 表格返回结构化单元格矩阵。
- 记录表格序号、段落序号和文档顺序。
- 后续按真实需要支持批注、脚注、页眉页脚和图片说明。

### Excel

- 保留工作表名、单元格坐标和实际使用区域。
- 区分公式、缓存值、显示值和数字格式。
- 记录合并单元格。
- 将连续数据区域识别为 Table Block。
- 图表只在真实分析场景需要时增加，不在第一阶段恢复完整 Excel 视觉布局。

### PowerPoint

- 保留页码、形状类型和基础坐标。
- 区分标题、正文、备注、表格、图片和图表。
- Block 顺序优先参考版面位置，而不是简单 XML 文本顺序。
- 视觉内容理解交给视觉模型后备链路，不要求 XML 解析器推断图片含义。

### PDF

- 保留页码和文本块坐标。
- 对有文本层的 PDF 优先使用本地解析。
- 复杂表格按真实业务需要选择专门解析器。
- 没有文本层或文本质量过低时返回明确 OCR 建议，不静默生成错误内容。

## OCR 后备链路

OCR 不应替换原生解析，而是有条件后备：

```text
原生 Extractor
  ├─ 文本层有效 → 使用原生结果
  └─ requires_ocr / 质量过低
       → OCR Provider
       → 页面文字与坐标
       → DocumentBlock
       → 保存解析缓存
```

OCR Provider 可以是：

- 本地 OCR；
- 企业部署的 OCR 服务；
- 具备视觉能力的模型；
- 云厂商文档解析服务。

Provider 负责适配供应商接口，`DocumentService` 只依赖统一 OCR 结果，不绑定具体厂商。

OCR 必须保留：

- 页码；
- 文本块坐标；
- 识别置信度；
- Provider 和模型版本；
- 是否经过人工或模型修正。

## 多文档联合分析

多文档分析不应创建另一套“文档项目”。它仍然以当前执行现场授权的多个附件为边界。

```text
多个 attachment_id
  → 各自解析并缓存
  → search_document 分别召回相关 Block
  → 模型联合比较
  → 回答中携带各自来源位置
```

典型场景：

- 三份供应商报价 Excel + 一份采购需求 Word；
- 合同初稿 + 企业制度 + 对方修改稿；
- 财务报表 + 经营汇报 PPT + 补充 PDF；
- 标书要求 + 技术方案 + 报价清单。

## 缓存与数据库

继续沿用当前解析缓存原则：

- 解析结果属于当前 Agent。
- 使用会话、附件 ID、内容 SHA-256、Extractor ID 和版本共同隔离。
- 文件内容变化或 Extractor 版本升级后重新解析。
- Block 与来源索引可以作为现有解析缓存结构的升级内容，不优先增加新的业务表。
- 实施时应使用现有数据库升级机制平滑迁移，不能要求删除旧 Agent 数据库。

## 安全边界

- 工具只接受 `attachment_id`，不接受任意绝对路径。
- 只读取当前 ToolExecutionContext 授权的附件。
- Desktop 不直接操作 Agent 的附件文件。
- 文档解析器不自动执行宏、嵌入脚本或外部链接。
- 加密文档返回明确错误，不尝试绕过密码。
- OCR 或云解析属于外部数据发送，未来必须纳入服务配置、权限和隐私提示。

## 分阶段实施建议

### 阶段 A：来源定位与结构块

- 增加 `DocumentBlock` 和 `SourceLocation`。
- 优先增强 DOCX 段落/表格和 XLSX 单元格范围。
- 保持 `read_document` 兼容现有调用方式。

### 阶段 B：文档搜索和结构化表格

- 增加 `search_document`。
- 增加 `extract_table`。
- 支持多附件联合查询和稳定来源引用。

### 阶段 C：PDF 与 OCR

- 增加文本质量判断。
- 接入可配置 OCR Provider。
- 保存页码、坐标、置信度和解析版本。

### 阶段 D：视觉结构理解

- PPT 图片、图表和布局理解。
- PDF 复杂版面和图表理解。
- 只在真实业务任务需要时调用视觉模型，避免无条件增加成本。

## 暂不包含

- 重做现有 `read_document`。
- 新增独立文档管理页面。
- 在 Desktop 内复制完整 Office 编辑器。
- 自动执行 Office 宏或嵌入脚本。
- 为每种格式暴露一组 Agent 工具。
- 在没有真实需求验证前追求完整恢复 Word、Excel、PPT 的全部视觉特性。

## 后续启动条件

出现以下真实问题之一时，再启动对应阶段：

- 合同审查无法定位原始条款；
- 供应商比价因合并表头或单元格坐标丢失而出错；
- 大型文档逐段读取成本过高；
- 扫描 PDF 无法处理；
- PPT 图文关系影响结论；
- 多文档结论无法提供可核验来源。

首个推荐验证场景：

> 上传三份供应商报价 Excel 和一份技术要求 Word，要求 Agent 完成结构化比价、指出异常项，并输出带来源位置的采购建议。

这个场景能够同时验证表格结构、跨文档检索、来源引用和最终文档交付，但不依赖 Project、Process 或 Assignment 的进一步设计。
