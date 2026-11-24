# 滨堤计量资料中心

归档员验收计量站日报，发行员把选定的冻结行按辖区或用途做成固定分件。各地镜像独立实收，再按站交班。资料管理员撤回发错的发布时，各地用同一撤回件结算自己的账。审计员可按原号查验当时的办理结果和出处。

## 运行

在项目根目录使用 Python 3.11，无第三方依赖。

```sh
python3 -B check_project.py
python3 -B -m examples.demo
```

正式回归入口 `check_project.py` 由运行环境提供。单独导出源码时可以直接运行完整套件。

```sh
python3 -B -m unittest discover -s tests -t .
```

演示以 `examples/day.json` 为输入，在临时目录建一座源库和两座镜像库。东区收到 P 的两件及 Q 的重叠件，西区只收到 P 的第一件。源库关闭后，东区退出 11 L、余 7 L，西区退出 7 L、余 0 L。西区首次收到 P 的迟件仍为零。`examples/expected.json` 保留独立手算预期，演示从实际结果取值并核对后打印单行场景结果。

## Python 接口

使用标准 `sqlite3.connect` 打开各自的数据库。每个业务调用拥有自己的事务，请传入没有进行中事务的连接。低层存储方法由业务入口在事务内调用。源库依次调用 `initialize_freeze`、`initialize_release` 和 `initialize_withdrawals`，镜像调用 `initialize_mirror(db, stations)`。这些初始化可重跑。镜像只在首次初始化时使用初始站点清单。可以在本地写事务中调用 `register_station` 登记额外空站，合法实收也会登记新站。

| 接口 | 输入与结果 |
| --- | --- |
| `lake.intake.freeze.freeze(db, batch)` | `BatchInput(station, name, rows)` 的 `rows` 是有序 `SourceRow(row_id, litres, Provenance(record, line))`。返回冻结批号、按原序冻结的事实和回执。站点和批名共同定位一个批。 |
| `lake.release.issues.issue(db, request_id, fact_ids, parts)` | `fact_ids` 是不重复的非空事实号序列，`parts` 将这些事实划分为有序非空分件。返回发布号、原件与发行回执。所选成员可与其他发布重叠。 |
| `lake.release.withdrawals.withdraw_issue(db, request_id, publication_id)` | 返回固定撤回件和发行回执。同一发布的后续撤回请求复领该固定结果。原分件继续按号保管。 |
| `lake.mirror.acceptance.accept(db, document)` | 接受分件、撤回件或其 JSON 表示。返回 `received`、`withdrawn` 或 `late`，以及适用的回执和撤回调整。一次调用办理一件。 |
| `lake.book.queries.station_book(db, station)` | 返回原事实及出处、行数和整升合计。明细按原事实号稳定排序。`withdrawal_adjustment(db, notice_id)` 读取实际退出明细及逐站净差。 |
| `lake.audit.history.replay(db, number)` | 在源库可按冻结批号、发布号或撤回件号查原结果，在镜像可按原件号查本地回执、出处和撤回调整。未知号报 `HistoryNotFound`。 |

`encode_document` 和 `decode_document` 在 `lake.release.formats` 中提供 V1 JSON 编解码。件在本地以同号及完整规范内容绑定，同号异件报 `DocumentConflict`。源端同号异参报 `RequestConflict`，选件错误报 `MemberSelectionError`，非法值或非法件形状报 `ValueError`，未知站报 `UnknownStation`。发布或源撤回的办理号在各自的办理类别内绑定。同一资料中心的固定事实号、发布号、件号及回执号为不透明标识。仅交付本站资料中心发行的材料，接纳会校验类型、结构、身份绑定和已知事实一致性。

## 核算与失败边界

整升值须为严格的 Python `int`，可为负数或零。V1 交付件及数据库以规范十进制文本保存升数，账目用整数运算。不同原行即使值相同也分别计量，同一事实跨发布只计一行。已登记空站返回空明细、零行和零升。撤回调整以本地结算前后的集合差为准，净差为结算后减结算前。撤回办完后，已正式实收的原件可按原号复领；未实收的迟件无成功回执。镜像的依据、终态、账目、调整和回执一起提交。`accept(..., fail_before_commit=True)` 可触发真实提交前回滚，供独立读取及重试演练。复领历史不会改变当前账。
