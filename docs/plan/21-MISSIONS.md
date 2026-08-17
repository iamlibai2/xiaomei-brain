# Mission：长期自主工作的最小内核

## 1. 目的

Mission 用来承载需要跨多次自主行动、持续数天或更久才能完成的责任，例如持续推广产品、长期维护客户关系或逐步完善一套内容资产。

Mission 不是一次 ReAct、不是严格 Workflow，也不复用 Goal/PACE、Assignment、Project 或 Workspace 的领域状态。它只记录长期责任、当前事实、下次可行动时间和停止条件；每次实际工作仍由同一个 Agent 在隔离 Core 中自由完成。

## 2. 核心边界

- **Intent 是唯一自主出口**：定时器、学习结果、外部反馈和 Mission 到期都只产生 Signal；只有 L2 可以决定是否形成自主 Intent。
- **Mission 是责任**：保存目标、责任人物、行动边界、成功标准、作业指南和检查点。
- **Skill 是指南**：Mission 只引用现有 Skill。Skill 可以调整工作策略，但不是 Mission 本身，也不能修改授权边界或停止条件。
- **Run 是一次推进**：每次由 `ADVANCE_MISSION` Intent 触发，在短生命周期隔离 Core 中执行，结束必须留下检查点。
- **Event 是事实**：创建、激活、等待、学习需求、运行结果和外部反馈都追加为事件，不覆盖历史事实。
- **Learning 是独立系统**：Mission 可以报告知识缺口；L2 决定是否产生 `LEARN` Intent，仍由现有 LearningEngine 学习。学习完成后再形成 Mission Signal。

## 3. 生命周期

Mission 第一版状态：

- `preparing`：正在讨论目标、边界、成功标准或选择 Skill。
- `active`：可以被 L2 选择推进。
- `waiting`：等待人物输入、外部条件或学习结果；必须保存明确的 `waiting_reason` 和结构化 `waiting_for`，并停止定时调度。
- `paused`：明确暂停，不参与自主决策。
- `completed`：成功标准已经满足。
- `stopped`：人物或 Agent 明确终止。

只有配置了有效 `skill_name` 的 Mission 才能从 `preparing` 进入 `active`。第一版不创建 Mission 私有 Skill；实施人员、用户或 Agent 可用 `create_skill` 将 Workspace 中讨论形成的作业指南安装为当前 Agent 的 Skill，并绑定给 Mission。Skill 立即热加载，不需要能力包或 Agent 重启。

Run 状态：`running / completed / interrupted / failed`。Agent 停止或实时执行器取消时，当前 Run 可以中断，但 Mission 本身仍保留。

## 4. 数据模型

### missions

- `id / title / objective`
- `status / priority`
- `accountable_person_id`
- `origin_session_id / origin_turn_id`
- `skill_name`
- `success_criteria / constraints / permissions`
- `checkpoint / progress_summary`
- `waiting_reason / waiting_for`
- `next_run_at / last_run_at`
- `created_by / revision / timestamps`

### mission_runs

- `id / mission_id / status`
- `trigger_intent_id / runtime_session_id`
- `result_summary / checkpoint / error_message`
- `started_at / completed_at`

### mission_events

- `id / mission_id / run_id`
- `event_type / summary / details`
- `created_at`

## 5. 信号与意图

MissionService 将所有 `active` 且 `next_run_at <= now` 的 Mission 投影为 `mission_due` Signal。Signal 包含 Mission ID、标题、责任人物、上次进展和到期时间，但不直接执行。

L2 意图决策新增：

- `ADVANCE_MISSION`：选择一个具体 Mission 推进；必须返回 `MISSION_ID`。
- `CREATE_MISSION`：Agent 自己判断某项长期责任值得建立；第一版只形成待讨论的 `preparing` Mission，不自动获得外部发布、付费或高风险权限。

用户在实时对话中明确创建、暂停、恢复或停止 Mission，属于直接命令，不需要再经过 L2。

进入 `waiting` 时必须清除 `next_run_at`。`waiting_reason` 用于向人物解释整体阻塞原因；`waiting_for` 保存系统可识别的具体条件（类型、键和说明）。确认条件满足后显式恢复为 `active`，同时清空等待信息并重新产生可推进时间。普通聊天不会自动恢复 Mission。

## 6. 一次推进

1. Mission 到期产生 `mission_due` Signal。
2. L2 在其他人物、学习、表达和休息信号之间做一次选择。
3. `ADVANCE_MISSION` Intent 进入 ActionDispatcher。
4. 通用 AutonomousBehaviorExecutor 创建隔离 Core。
5. MissionRunner 加载 Mission、全局 Skill 正文、最近事件和检查点。
6. Agent 自由使用现有工具完成一个有边界的工作片段。
7. Agent 调用 Mission 检查点工具或由 Runner 保存结果摘要。
8. Mission 更新进展和 `next_run_at`；Run 和 Event 记录事实；Activity 提供统一可观测性。

MissionRunner 不负责固定步骤，不判断“第几阶段必须完成”。Skill 提供领域方法，Mission 的成功标准约束结果，Agent 决定本次如何工作。

## 7. 外部行动边界

第一版 Mission 可由 Agent 创建，但外部发布、发信、付费、删除或其他不可逆行为必须在 `permissions` 中明确允许。未授权时 Mission 进入 `waiting` 并向责任人物询问，不把 Skill 中的文字视为授权。

## 8. 第一版交付范围

- Mission / Run / Event 的 SQLite 持久化和服务层。
- 创建、查询、修改、激活、暂停、恢复、停止和检查点工具。
- `mission_due` Signal 注入 L2。
- `ADVANCE_MISSION` Intent 和 ActionDispatcher 路由。
- 复用 AutonomousBehaviorExecutor 的隔离 Core 完成一次 Mission Run。
- 确定性加载 Mission 绑定的全局 Skill。
- Activity 记录 Mission Run。
- 基础单元测试。

暂不实现私有 Skill、多版本、审批流、组织权限、Mission 市场、旧 Goal/PACE 数据迁移和复杂自动重试。
