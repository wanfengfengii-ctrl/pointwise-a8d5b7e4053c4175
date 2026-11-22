# 泵站巡检交班台

使用 Python 3.11 标准库和本地 SQLite。模拟泵站白班登记应采范围、共用终端导出原始巡检行、签发区段清单并封班。夜班可断开来源，按号核对固定读数、原件及首执。

```sh
python3 -B check_project.py
python3 -B -m pump_rounds demo
```

完整回归入口 `check_project.py` 由运行环境提供。直接运行原单元测试可使用 `python3 -B -m unittest discover -v`。演示读取 `samples/recording.json`，在测试性质的临时目录创建归档并在退出时清理。

## 一次巡检交班

1. 值班员登记班次区段与点位顺序。样例的正式白班含北、西两区，终端初选是另行登记的东区值守页。重复初始化保留已有清册和人工选择。
2. 值班员可随时人工选区。每次人工操作产生新任次，包含与显示同值的选区。人工选区后，先前开启的临时覆盖失去恢复资格。新覆盖按开启先后优先，撤下谁只影响谁。
3. 采集员按原单号领单。领单绑定此班区段清册，打开覆盖并排队。重投原号同参返回原单与当前尝试，异参报冲突。已经撤下覆盖的单仍可核收原来的生成件。
4. 设备根据录制的生成事件读取当时实际生效的区段。原件固定生成号、尝试号、文件号和 SHA-256。重投同一生成身份返回已固定见证。单个尝试对应单个生成件，重用其中任一身份指向另一件会报冲突。
5. 下载员交入原字节和三项身份。回包相对于生成可乱序。身份或字节不符会拒收。身份正确但实际班次或区段不匹配时标记错区，可在原单下领取新尝试。取回的旧错区件仍按原尝试处理。
6. 校验员按固定清册核对原件。CSV 使用 UTF-8、精确表头 `point,value`，每条记录占一个物理行。显式 `NA` 表示缺测，各点须恰有一条原行。读数使用可带正负号和小数点的十进制记法。单位取自点位登记，`0.007` kPa 换算为 `7` Pa，无法精确表示为整数 Pa 的读数会拒收。清单保留原值及物理行号，按清册输出。零算有效读数，NA 只计缺测。
7. 签发员将合格实收冻结为区段清单。班册员提交本次使用的采集单号，逐区检查正式清单。待签实收仍属缺区。覆盖齐备时按清册顺序冻结引用及统计。区段清单或班册与对应首执同一事务提交。
8. 关闭来源并重开归档后，接班员按原号领取。班册带回相应区段清单、原字节和原行号。若签存途中失败，原号可重投，已经定稿的旧成果可以照常领取。

## 调用接口

先用 `storage.open_database(path)` 打开库，再用 `handover.archive.Archive(db)` 建立归档接口。所有事件按录制顺序调用，只有下载到达顺序可以与生成顺序不同。数据库连接由调用者关闭。

| 调用 | 返回和业务约束 |
| --- | --- |
| `roster.shifts.register(db, shift_id, sectors)` | `sectors` 是有序的 `(区段, [(点位, 单位), ...])`。重复点位、重复区段与未知单位拒绝。同号同清册可重投，同号异参拒绝。 |
| `roster.bootstrap.initialize(db, rosters, initial)` | `rosters` 是 `(班次, sectors)` 序列。`initial` 是 `(班次, 区段)`。只补缺项。 |
| `terminal.operator.select(db, shift_id, sector_id)` | 返回新人工选择。未知班次或区段报错且保留原状态。`terminal.overlays.OverlayState(db).effective_sector()` 返回当前 `(班次, 区段)`，未选时为空。 |
| `collection.orders.start(db, order_id, shift_id, sector_id)` | 返回 `(CollectionOrder, Attempt)`。跨班区段或同号异参拒绝。`resume_order(db, order_id)` 在最近尝试已判错区时开启新尝试。 |
| `terminal.generation.generate(db, source, attempt_id, generation_id, file_id)` | 返回固定的 `GeneratedExport`。`source` 使用 `terminal.recording.RecordedTerminal`。未知尝试不生成文件。`GenerationLedger(db).read_payload(file_id)` 读取原下载字节。 |
| `collection.downloads.receive(db, artifact)` | `collection.artifacts.read_download(attempt_id, generation_id, file_id, raw)` 构造待投原件。合格时返回 `AcceptedDownload`，真实错区返回 `Eligibility.WRONG_SECTOR`。错绑、未知尝试及行校验失败报错。 |
| `terminal.overlays.finish(db, order_id)` | 撤下该单覆盖并返回有效范围，未知单保持筛选。 |
| `handover.sector_lists.publish(archive, order_id)` | 返回 `SectorList` 和其中的首执。未正式实收时报错。已定稿同号复领原结果。 |
| `handover.shift_book.close_shift(archive, shift_id, order_ids)` | 返回 `ShiftBook` 或有序的 `MissingSectors`。每区至多指定一张本班采集单。已定稿班册可用同一组单号重投，传入顺序可变。 |
| `handover.retrieve.retrieve(archive, output_id, kind='sector')` | 按采集单号领区段，传 `kind='shift'` 按班次号领班册。返回固定结果及首执。未知或未定稿报 `no_output`。 |

输入、冲突、缺件等业务异常为 `errors.InspectionError`，其 `code` 区分失败原因。SQLite 写入错误原样返回，事务随之回滚。`recording.json` 分别给定排队、人工接管、生成、回包和定稿的顺序。演示中 A 的第一件在西区生成，切回北区才到达，因此 A 续采后才领取北区 7 Pa。B 领取西区 11 Pa。全班有效两点、缺测一点，极值 7 和 11 Pa，按北、西清册顺序领取。
