# 修复记录：共用导出终端的选区覆盖与错区判定

## 事故复盘（对照 INCIDENT.md）

白班初始值守页为东区。A 领北区单并开临时覆盖排队，值班员人工再选北区（同值仍产生新任次）；
B 随后领西区单并开覆盖，A 的 `f-A-1` 与 B 的 `f-B-1` 都在西区生效期间生成。
撤 B 后 A 的文件才回到北区交件。修复后的正确账：

- A 的 `f-A-1` 实际出处为 `day/west`，与 A 单绑定的 `day/north` 不符 → 判 `WRONG_SECTOR`，
  不出北区清单、不产生首执，原单 A 可续采；
- B 的 `f-B-1` 出处为 `day/west` → 合格，签西区 11 Pa 与首执 `sector:B`；
- A 续采的新尝试生成 `f-A-2`（`day/north`，7 Pa）→ 签北区 7 Pa 与首执 `sector:A`；
- 两单覆盖全部撤下后，显示保留最后一次人工选择 `day/north`，不再跳回东区；
- 断源重开后按原号仍可领取两张已冻结清单、原字节、物理行号、出处与首执。

## 根因

### 根因一：人工选择与临时覆盖共用同一存储单元，人工改选不能废止旧覆盖

旧实现在 `terminal/overlays.py` 中把临时覆盖直接写进 `operator_selection` 单行表，
开启覆盖时把当时显示值快照到 `terminal_overlays.previous_shift_id/previous_sector_id`，
撤覆盖时只要当前显示仍等于本单目标就无条件回滚该快照。问题：

1. 人工选择（`terminal/operator.select`，同值也递增 `revision`）与临时覆盖没有分离，
   人工改选后旧覆盖仍持有恢复资格；
2. 多单叠加时按各自快照链式回滚，两单撤完最终回滚到初始登记的 `desk/east`——
   即事故中的"撤完跳回东区"；
3. 没有"显示最近仍有效的临时选择，否则显示最后一次人工选择"的判定结构。

### 根因二：生成件登记的是工单绑定区段而非实际生成区段，错区判定不可达

- `terminal/generation.py` 的 `generate` 虽按当时生效区段读取录制源，
  却把导出请求（工单）上的 `shift_id/sector_id` 写入 `GeneratedExport`，
  实际出处丢失；
- `collection/eligibility.py` 只核对三项身份与 SHA-256，
  从不比较生成件实际班次/区段与工单班次/区段，`Eligibility.WRONG_SECTOR` 永远不会返回；
- 因此 A 的西区 11 Pa 件通过核收、被冻结进北区清单并拿到北区首执。
  即使两区文件字节完全相同，系统也无法按出处各自认定。

## 修复方案（遵循 README.md 的调用与签存规则，接口签名不变）

1. `storage.py`
   - `terminal_overlays` 改为 `(opened, order_id UNIQUE, operator_revision)`，
     只记录该单覆盖开启时的人工选择任次，不再快照选区值；
   - `generated_exports` 增加实际出处列 `shift_id/sector_id`，与 `export_queue`
     上的工单绑定列分开。
2. `terminal/overlays.py`
   - `operator_selection` 只承载人工选择，开覆盖不再覆写它；
   - `OverlayState.effective_sector()`：在 `operator_revision >= 当前人工任次`
     （即人工改选之后仍有效）的覆盖中，按开启顺序取最新一单的目标区段；
     没有有效覆盖时返回最后一次人工选择；无任何选择时返回 `None`；
   - `open_overlay` 记录当前人工任次；重投/续采重开只刷新本单，不影响他单；
   - `finish` 只删除本单覆盖；未知单删零行，筛选保持不变。
3. `terminal/generation.py`
   - 生成时把**当时实际生效**的班次/区段写入 `generated_exports` 并固化进
     `GeneratedExport`；台账查询改读生成件自身的出处列；重投同身份仍返回原固定见证。
4. `collection/eligibility.py`
   - 身份错绑、摘要不符仍按原错误码报错；通过后再比较
     `(export.shift_id, export.sector_id)` 与 `(order.shift_id, order.sector_id)`，
     不符返回 `Eligibility.WRONG_SECTOR`（字节相同也以出处为准）。
   - 错区在 `collection/downloads.receive` 中把尝试标记为 `wrong_sector`、
     不写实收、不触发行校验；原单经 `resume_order` 续采新尝试，旧错区件重投仍判错区。

## 新增回归（tests/test_incident_fix.py，原 23 条断言全部保留未改）

- 人工同值改选后旧覆盖丧失恢复资格，撤完显示最后一次人工选择；
- 未知单撤下保持筛选、撤单互不影响、重复撤单无副作用；
- 选区状态经关闭/重开数据库保持；
- 错区续采时他单覆盖与人工选择共存的次序；
- 错区件阻断清单与首执、旧件重投仍错区、续采后正常签存并领班册；
- 两区字节完全相同仍按实际出处分别认定；
- 跨班错区同样判错区；行校验失败不误标错区、尝试保持 waiting；
- 断源重开后已冻结成果、原件与首执照常领取，重复签发返回同一固定结果。

## 验证结果

- `python3 -B check_project.py`：31 个测试（原 23 + 新增 8）全部 PASS，退出码 0；
- `python3 -B incident.py`：late / identical-early / identical-late 三段录制
  期望与实测逐字段一致，退出码 0；
- `python3 -B -m pump_rounds demo`：普通白班交班演示通过，
  北区 7 Pa（f-A 续采件）、西区 11 Pa（f-B）、缺测 1 点、极值 7/11 Pa，
  断源重开领取结果与班册一致，退出码 0。
