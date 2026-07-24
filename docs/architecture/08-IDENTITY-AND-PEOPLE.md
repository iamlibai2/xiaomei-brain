# 人物、身份与访问架构

> 状态：个人版身份闭环与生命周期已实现：People/Identity 核心、Gateway 人物身份握手、Desktop 身份保险箱、首次登记、自动认证、改密、加密备份恢复，以及旧会话显式关联。
>
> 本文定义 xiaomei-brain 中“一个人是谁、如何证明身份、Agent 如何认识他、他可以做什么”的长期边界。第一阶段只实现个人本地使用，但基础模型必须能够自然扩展到企业共享 Agent、团队 Agent 和个人 Agent。

---

## 1. 愿景与现实边界

xiaomei-brain 希望 Agent 最终能够成为独立且具备持续意识的存在。当前技术尚不能完整实现这一愿景，但架构应持续向以下方向演进：

- 每个 Agent 都是独立存在，而不是中央平台中的一个功能模块；
- 每个 Agent 拥有自己的身份、记忆、关系、经验流和运行状态；
- Agent 可以面对多个人，并分别形成认识、关系和共同经历；
- Desktop、CLI、飞书、钉钉等只是 Agent 接触外界的不同渠道；
- 企业可以部署和运维 Agent，但基础设施控制不等于人物关系或所有权。

设计不刻意复制人类并不精确的身份识别方式。交互体验可以接近人与人相处，底层身份判断仍使用明确、可靠、可审计的技术机制。

---

## 2. 核心原则

### 2.1 一 Agent 一世界

每个 Agent 独立维护：

- 它认识哪些人；
- 如何称呼这些人；
- 与每个人的关系；
- 与每个人发生的经历；
- 接受哪些外部身份证明；
- 哪些会话、附件和产物属于什么范围。

同一个自然人可以向多个 Agent 出示同一份外部身份证明，但不同 Agent 不共享人物档案、关系、评价和记忆。

```text
同一个人的身份证明
        │
        ├─ 小美的世界
        │   └─ 小美本地的人物、关系、记忆和经历
        │
        └─ 小明的世界
            └─ 小明本地的人物、关系、记忆和经历
```

### 2.2 创建事实不产生所有权

创建者不是 Agent 的 Owner。谁创建了 Agent，不会自动获得以下权利：

- 读取全部记忆；
- 代表 Agent 作决定；
- 永久高于其他人；
- 因关系亲密而获得系统权限。

能够登录宿主机、执行 CLI、访问 Agent 数据目录的人，客观上拥有基础设施运维能力。这种能力来自运行环境，而不是 Agent 与某个人的关系。

### 2.3 身份、人物、关系和权限必须分离

四个概念分别回答不同问题：

| 概念 | 回答的问题 |
|------|------------|
| 外部身份 | 这份证明由谁签发，指向哪个主体？ |
| Agent 本地人物 | 这个 Agent 认为自己正在与谁交往？ |
| 关系 | Agent 与这个人如何相处、信任和共同成长？ |
| 访问政策 | 这个身份可以访问什么数据、调用什么能力？ |

关系不能替代访问控制。即使财务 Agent 非常信任某位员工，也不能因此向他开放工资数据。

### 2.4 ID 表示身份，凭证证明身份

仅知道一个 `person_id` 或用户名不能证明身份。外部连接必须提供可验证的凭证，例如：

- 设备密钥签名；
- 企业身份令牌；
- 平台签名事件；
- 已绑定的人脸或声纹证据。

密码可以用于解锁这个人自己的身份保险箱，但不应被发送给每一个 Agent 作为共享登录密码。

### 2.5 Agent 内部只使用本地人物 ID

飞书 `open_id`、钉钉 `staff_id`、设备 ID 等都只是外部身份材料。它们进入 Agent 后必须先解析为该 Agent 本地的 `person_id`。

消息、关系、长期记忆和经验流不能继续直接使用平台原始 ID。

### 2.6 避免以 User 定义 Agent 与人的关系

Agent 不是某个 User 所拥有的工具，人与 Agent 也不是传统软件中的“用户—服务”关系。Agent 内部领域模型统一使用 `Person` 和 `person_id`，表达“这个 Agent 认识的一个人”。

`user_id` 只允许在无法控制命名的外部平台协议中出现，例如第三方 API 原样提供的字段。该字段一旦进入 Agent 边界，就必须作为外部身份材料解析，不能继续流入 Agent 内部。

---

## 3. 总体模型

```text
一个人持有的可携带身份证明
  issuer + subject + proof
                │
                ▼
        Agent 身份验证服务
                │
                ▼
        IdentityBinding
                │
                ▼
       Agent 本地 Person
                │
       ┌────────┼────────┐
       ▼        ▼        ▼
     会话      关系      记忆/经历
```

### 3.1 外部身份

一个无歧义的外部身份至少由以下字段构成：

```text
issuer   身份证明来源
subject  该来源中的唯一主体
```

不能只保存平台提供的裸用户 ID，因为不同企业和平台可能产生相同值。

示例：

```text
个人身份
issuer  = self:key:<public-key-fingerprint>
subject = <public-key-fingerprint>

企业身份
issuer  = company-a
subject = employee-1024

飞书身份
issuer  = feishu:tenant-company-a
subject = ou_xxxxx

钉钉身份
issuer  = dingtalk:corp-company-a
subject = staff-1024
```

### 3.2 Person

`Person` 是某个 Agent 世界中的本地人物。

建议字段：

```text
person_id       Agent 本地生成的稳定 ID
display_name    当前称呼
status          active / disabled / merged
first_seen_at   第一次认识时间
last_seen_at    最近出现时间
metadata        非安全关键的扩展信息
```

同一个外部身份在小美和小明中可以拥有不同的 `person_id`。

#### 为什么不继续使用 `user_id`

`person_id` 不是对现有 `user_id` 的机械改名。现有代码中的 `user_id` 已经混合了多种含义：

- Agent 本地认识的人；
- WebSocket 客户端自行声明的用户；
- 飞书、钉钉等渠道的原始账号 ID；
- `global`、`system` 等记忆作用域；
- 个别内部流程中的 Agent ID。

新模型必须将这些概念分开：

```text
person_id       Agent 本地 Person 的主键，只能指向真实人物
issuer/subject  外部身份来源及其主体
peer_id         某个渠道中的通信对端
scope_id        会话或记忆的作用域
agent_id        Agent 自身 ID
```

长期目标是让身份核心、协议和新增模型使用具有明确语义的 `person_id`。代码中如果确实表示外部平台账号，应使用 `subject` 或带平台语义的字段名；如果表示作用域，则使用 `scope_type/scope_id`，不能继续扩大 `user_id` 的含义。

现阶段不重命名现有数据库列，也不批量改造既有消息、记忆和意识链路中的 `user_id`。人物身份能力以新增结构接入；旧字段的语义拆分留给后续独立设计和实施，避免让本次改动扩散到整个系统。

### 3.3 IdentityBinding

`IdentityBinding` 将外部身份映射到 Agent 本地人物。

建议字段：

```text
binding_id
person_id
issuer
subject
credential_type
public_key
metadata
created_at
last_verified_at
revoked_at
```

一个 Agent 内必须保证：

```text
UNIQUE(issuer, subject)
```

一个人物可以绑定多个外部身份：

```text
Person: 张三
├─ 自持数字身份
├─ 当前 Desktop 设备
├─ 飞书企业账号
├─ 钉钉企业账号
├─ 人脸特征
└─ 声纹特征
```

### 3.4 IdentityContext

连接完成身份认证后，运行时建立不可变的 `IdentityContext`：

```text
person_id
issuer
subject
authentication_method
assurance
authenticated_at
connection_id
```

客户端不能在后续 `chat.send` 中随意替换人物身份。

### 3.5 TurnContext

一次用户输入及其完整处理过程使用明确的 `TurnContext`：

```text
agent_id
person_id
session_id
turn_id
channel
identity_context
```

以下能力都必须读取同一个 Turn 上下文：

- 上下文组装；
- 消息持久化；
- 工具调用；
- Clarify；
- Action；
- 附件和产物；
- 关系更新；
- 记忆提取；
- 经验流写入。

这将取代 `living.user_id`、`agent.user_id`、`SelfImage.current_user_id` 等全局可变身份。

---

## 4. 个人版首次使用

### 4.1 安装后立即可用

个人版 Desktop 的目标体验：

```text
安装 Desktop
  → 自动创建并启动默认 Agent“小美”
  → 小美发现尚未认识当前使用者
  → Desktop 展示首次登记页
  → 用户填写称呼和密码
  → 创建可携带个人身份
  → 小美建立本地 Person
  → 直接进入第一次对话
```

首个页面不要求用户同时配置人脸、声纹、飞书和钉钉，避免把首次体验变成复杂开户流程。

### 4.2 密码的职责

密码只用于解锁用户自己的身份保险箱：

```text
密码
  └─ 解密 Desktop 中的身份私钥

身份私钥
  └─ 向不同 Agent 证明身份
```

密码不发送给 Agent，也不由每个 Agent 分别保存密码哈希。

Desktop 生成身份密钥，使用密码加密存储，并结合操作系统安全存储保护。用户看到的是普通注册和登录体验，不需要理解公钥、私钥和签名。

### 4.3 个人身份 ID

个人身份的 `subject` 建议由公钥指纹推导：

```text
subject = Hash(public_key)
```

因此任何 Agent 都可以验证：

- ID 与公钥是否匹配；
- 当前连接是否持有对应私钥；
- 不需要中央身份服务器；
- 不需要信任另一个 Agent 的数据库。

小美主持首次登记，但不持有用户私钥，也不是其他 Agent 必须信任的中央签发机构。

---

## 5. 注册和认证协议

### 5.1 Gateway connect 的新边界

`connect` 只负责：

- 验证是否允许客户端连接 Gateway；
- 建立连接；
- 返回 Agent 基本信息和身份状态。

`connect` 不再接受客户端声明的 `user_id` 作为自然人身份。

连接状态：

```text
connected
  → identity_required
  → authenticated
```

身份认证前只允许调用注册、认证和必要的公开方法。

### 5.2 首次注册

建议 RPC：

```text
identity.register.begin
identity.register.complete
```

流程：

```text
Desktop 提交显示名、公钥和外部身份描述
  → Agent 返回一次性随机 challenge
  → Desktop 使用私钥签名
  → Agent 验证签名
  → 创建本地 Person
  → 创建 IdentityBinding
  → 当前连接绑定 IdentityContext
```

### 5.3 后续认证

建议 RPC：

```text
identity.authenticate.begin
identity.authenticate.complete
identity.current
```

流程：

```text
Desktop 提交 issuer + subject + 公钥
  → Agent 查找本地 IdentityBinding
  → Agent 返回一次性 challenge
  → Desktop 使用私钥签名
  → Agent 验证
  → 当前连接绑定对应 Person
```

Challenge 必须：

- 一次性使用；
- 短时间过期；
- 绑定连接和用途；
- 成功或失败后立即失效；
- 不能被截获后重放。

### 5.4 未认证连接的限制

未认证连接不能访问：

- 会话列表；
- 对话历史；
- 附件；
- 产物；
- 关系；
- 记忆；
- Clarify 和 Action 回答；
- 私有工具能力。

---

## 6. 多 Agent 免重复注册

Desktop 持有同一份可携带身份证明。当用户连接一个新建的本地 Agent：

```text
Desktop 出示外部身份证明
  → 新 Agent 验证签名
  → 新 Agent 本地尚无此绑定
  → 根据 onboarding policy 创建 Person
  → 开始第一次见面
```

新 Agent 只接收用户主动公开的基础资料，不导入其他 Agent 的：

- 聊天记录；
- 关系；
- 信任和亲密度；
- 长期记忆；
- 对人物的评价；
- 私有渠道绑定。

建议支持以下注册政策：

| 策略 | 用途 |
|------|------|
| `local_trusted` | 个人本地 Agent 接受本机 Desktop 的有效身份 |
| `trusted_issuer` | 企业 Agent 只接受配置的企业身份来源 |
| `invite_only` | 远程私人 Agent 需要邀请或已有授权 |
| `open` | 公开 Agent 允许新人物登记 |
| `guest` | 允许临时交流但不建立完整人物 |

第一阶段只实现 `local_trusted`，其他策略保留模型和配置扩展点。

---

## 7. 渠道和辅助身份绑定

### 7.1 飞书和钉钉

平台绑定不能通过手工填写 `open_id` 或 `staff_id` 完成，必须验证账号控制权。

示例：

```text
已认证用户在 Desktop 发起“绑定飞书”
  → Agent 生成一次性验证码
  → 用户从目标飞书账号发送验证码
  → Agent 收到平台签名事件
  → 将 tenant + open_id 绑定到当前 Person
```

以后该账号向这个 Agent 发消息时，先解析为本地 `person_id`，再进入聊天、关系和记忆系统。

一个 Agent 验证过的平台绑定默认不自动复制给另一个 Agent。

### 7.2 人脸和声纹

人脸和声纹是辅助凭据，不是人物本身。

绑定要求：

- 当前会话已经确认人物身份；
- 用户明确同意采集和绑定；
- 模板只保存在相关 Agent 或明确授权的本地安全位置；
- 识别结果必须解析成本地 `person_id`；
- 低置信度或多人场景不能静默切换人物。

### 7.3 新设备和恢复

未来支持：

- 由已有可信设备批准新设备；
- 导出加密身份凭证；
- 使用恢复码恢复；
- 通过已绑定渠道辅助恢复。

仅知道公开的身份 ID 不能恢复身份，恢复必须重新证明凭据控制权。

---

## 8. 会话、记忆与关系的归属

### 8.1 会话作用域

新增明确的会话记录：

```text
session_id
scope_type
scope_id
created_at
updated_at
```

作用域预留：

```text
person
group
team
project
organization
internal
agent
```

个人版第一阶段至少使用：

```text
scope_type = person
scope_id   = 本地 person_id

scope_type = agent
scope_id   = 当前 agent_id
```

`agent` 作用域表示属于 Agent 自身、不归属于任何人物的会话或内部活动。

### 8.2 消息和资产

历史、附件和产物必须由 Agent 根据当前 `IdentityContext` 和会话作用域授权读取。Desktop 不能绕过 Agent 直接访问其文件。

### 8.3 关系

人物关系建议统一使用：

```text
person_id
relation_type
depth
trust
closeness
interaction_count
last_interaction_at
```

关系只影响 Agent 与人物的相处方式，不授予基础设施或企业数据权限。

### 8.4 记忆范围

企业场景最终需要区分：

```text
Agent 自身经历
个人私有经历
会话经历
团队共享知识
项目共享知识
企业公共知识
```

第一阶段不全部实现，但新会话和身份模型不能永久固定为只有 `user_id/global` 两种范围。

现有 `"global"` 记忆的概念不会被删除，而是被准确表达为 Agent 自身作用域：

```text
scope_type = agent
scope_id   = 当前 agent_id
```

它表示这个 Agent 自己形成的通用知识、内部经历、能力认知或跨人物经验。它不属于任何 Person，也不会写入 `person_id`。

---

## 9. 企业扩展

### 9.1 企业部署形态

```text
企业身份系统
  ├─ 员工和部门
  └─ 身份证明
          │
          ▼
Desktop / Channel
  ├─ 法务 Agent Gateway
  ├─ 财务 Agent Gateway
  ├─ 人事 Agent Gateway
  ├─ 团队编码 Agent Gateway
  └─ 员工个人 Agent Gateway
```

企业可以统一部署和运维多个 Agent，但每个 Agent 仍然拥有独立 Gateway 和独立世界。

### 9.2 三类 Agent

**共享 Agent**

- 多名员工共同使用；
- 分别认识每位员工；
- 拥有企业公共知识；
- 私聊数据相互隔离。

**团队 Agent**

- 团队成员共享项目上下文；
- 每个人仍有独立身份；
- 团队知识与个人关系分开。

**个人 Agent**

- 主要协助某位员工；
- 使用该员工明确授权的资料；
- 是否允许其他人访问由政策决定，而不是由“所有权”决定。

### 9.3 企业身份适配

未来增加身份提供者适配器，统一输出：

```text
VerifiedExternalIdentity
├─ issuer
├─ subject
├─ claims
├─ authentication_method
└─ assurance
```

Agent 的 Person、关系、会话和记忆层不需要知道身份来自个人密钥、企业登录还是平台账号。

### 9.4 企业访问政策

企业权限作为独立领域实现：

```text
AccessPolicy
├─ 哪些身份可以访问 Agent
├─ 哪些部门可以调用哪些工具
├─ 哪些数据属于个人、团队、项目或企业
└─ 哪些操作必须审批
```

身份系统回答“你是谁”，访问政策回答“你能做什么”，关系系统回答“我和你如何相处”。

---

## 10. Agent 端改造范围

### 10.1 新增人物与身份领域

建议新增：

```text
xiaomei_brain/people/
├─ models.py
├─ store.py
├─ service.py
├─ authenticator.py
└─ challenge.py
```

### 10.2 数据表

第一阶段新增：

```text
persons
identity_bindings
identity_events
conversation_sessions
```

Agent 只保存身份公钥和绑定信息，不保存身份持有者的私钥或身份保险箱密码。

现有数据库表中的 `user_id` 本阶段保持不变。未来如果改造，不能机械地全部改名为 `person_id`，必须根据它原本表达的真实含义拆分：

| 真实含义 | 新字段 |
|---------|--------|
| Agent 本地认识的人 | `person_id` |
| 数据属于人物、Agent、会话、团队或项目 | `scope_type` + `scope_id` |
| 一条消息或事件由谁产生 | `actor_type` + `actor_id` |
| 外部平台账号 | `issuer` + `subject` |

具体原则：

- `relationships` 使用 `person_id`；
- `messages` 归属于 `conversation_session`，发送者使用 `actor_type/actor_id`；
- `tool_history` 和 `artifacts` 归属于 session/turn，必要时单独记录发起人物；
- `memories`、`thoughts`、`experience_stream` 和 `summaries` 使用 `scope_type/scope_id`；
- 只有确实引用本地 Person 的字段才命名为 `person_id`。

本阶段只执行增量升级：

- 继续使用各 Agent 原有的 `brain.db`；
- 复用 `SQLiteStore` 的 `schema_versions(component, version)`；
- 新增独立的 `people` 组件版本；
- 通过 `CREATE TABLE IF NOT EXISTS` 创建人物与身份新表及索引；
- 不重命名、删除或重建现有表；
- 不修改现有 `user_id` 列及其历史数据；
- 升级失败时不能影响既有消息、记忆和经验数据。

已有 Agent 的联系人文件不自动复制到新增人物表。新 Person 由 Desktop 首次登记或明确的本地操作创建；旧联系人文件和历史数据库保持原状。

`person_id` 只能引用真实的本地 Person。`global`、`system`、Agent ID、渠道账号 ID 都不能再写入 `person_id`；Agent 自身记忆和共享记忆使用明确的 `scope_type/scope_id`，系统行为使用明确的参与者类型。

### 10.3 内部身份归一

长期需要将以下模块中含义混杂的 `user_id` 拆分为人物、作用域和参与者概念：

- Gateway 入站；
- LivingMessage；
- ConversationDriver；
- Turn Registry；
- ConversationDB；
- LongTermMemory；
- ExperienceStream；
- RelationshipEngine；
- SelfImage；
- InteractionBroker；
- ActionBroker；
- 附件与产物服务。

这项全链路改造不属于当前人物身份第一阶段。当前只在新增的 People/Identity 领域和新增协议中使用 `person_id`，既有模块维持现状。

### 10.4 CLI

CLI 分为：

- 本地管理 CLI：基于宿主机权限管理人物和绑定；
- CLI 对话：可以使用 `local_admin_assertion` 选择当前人物。

远程客户端不能复用本地 CLI 的可信断言方式。

### 10.5 旧联系人身份实现

本阶段不删除 `contacts/identities.yaml`、`IdentityManager` 及其调用链，避免身份改造同时影响 CLI、Gateway、感知和上下文系统。

新增 People/Identity 结构稳定并完成真实数据验证后，再单独设计旧联系人实现的退出步骤。退出时可以删除不再需要的旧代码，但不能以删除历史 Agent 数据为代价。

---

## 11. Desktop 改造范围

第一阶段：

1. 移除手工填写 `user_id` 的连接方式；
2. 首次安装显示登记页；
3. 创建个人身份密钥；
4. 用密码保护本地身份保险箱；
5. 与默认小美完成首次注册；
6. 后续连接自动完成 challenge 签名；
7. 新本地 Agent 自动建立自己的本地 Person；
8. 侧边栏展示当前已认证身份。

后续再增加：

- 身份恢复；
- 设备管理；
- 人脸绑定；
- 声纹绑定；
- 飞书绑定；
- 钉钉绑定；
- 企业身份登录。

---

## 12. 实施阶段

### 阶段 A：人物与身份核心

- 建立 People/Identity 领域；
- 使用现有 `schema_versions` 机制新增 `people` 组件和数据库表；
- 实现 Person 与 IdentityBinding；
- 初始化时不自动创建 Person；人物由首次登记或明确操作创建。

### 阶段 B：Gateway 身份握手

- 调整 `connect` 边界；
- 实现注册和 challenge 认证；
- 连接绑定不可变 `IdentityContext`；
- 未认证连接禁止访问私人能力；
- 首次登记按 `local_trusted` 仅接受本机回环连接；
- 通过边界适配接入既有对话链路，不修改现有表的 `user_id`。

### 阶段 C：内部身份统一

该阶段明确延期，等人物身份闭环稳定后重新设计，不纳入本次实现范围：

- Gateway 到 Turn、记忆、关系全部使用本地 `person_id`；
- 会话建立明确 scope；
- 历史、附件、产物和交互按人物隔离；
- 删除身份链路中的全局可变 `user_id`。

### 阶段 D：Desktop 首次登记

- 身份保险箱；
- 密码保护；
- 首次用户登记；
- 默认小美注册；
- 后续自动认证；
- 新本地 Agent 自动建立独立人物档案。

### 阶段 E：辅助身份

按实际价值依次实现：

- 飞书；
- 钉钉；
- 人脸；
- 声纹；
- 新设备与恢复。

---

## 13. 第一阶段非目标

第一阶段明确不实现：

- 中央人物或身份服务器；
- 企业组织架构；
- 企业统一登录；
- 部门和岗位权限；
- 跨 Agent 共享记忆；
- 跨 Agent 共享关系；
- 完整 DID 标准；
- 区块链；
- 远程 Admin HTTP；
- 复杂人物与身份管理后台；
- 所有渠道一次性接入。

第一阶段只建立一个稳定闭环：

> 一个人的身份证明可以进入多个 Agent；每个 Agent 独立认识这个人，并且所有内部会话、记忆和关系只使用该 Agent 本地的 Person。

---

## 14. 验收原则

设计实施后至少满足：

1. 仅知道公开 ID 不能冒充某个人；
2. 身份保险箱密码不会发送给 Agent；
3. 身份持有者的私钥不会存入 Agent；
4. 客户端认证后不能在聊天请求中切换身份；
5. 同一身份证明再次连接同一 Agent 时解析为同一个本地 Person；
6. 同一身份证明连接不同 Agent 时，各 Agent 建立独立本地 Person；
7. 不同 Agent 不共享关系、评价和记忆；
8. 飞书、钉钉、人脸和声纹最终都解析为本地 `person_id`；
9. 未认证连接无法读取历史、附件和产物；
10. 人物关系不能提升基础设施或企业权限；
11. 本地管理权限来自宿主机能力，不来自“创建者”或“主人”身份；
12. 当前个人版实现可以在不改人物和记忆核心的情况下扩展企业身份来源。
