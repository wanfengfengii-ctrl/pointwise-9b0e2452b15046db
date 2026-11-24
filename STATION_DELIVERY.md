# 滨堤计量数仓的分站交班

固定原件有时混装几个站的日报。站件正式入账后，后续收到其他站件或原整件可以继续办理。同一资料中心的账仍按原事实去重，并沿用原发布的撤回件。README.md 中的 V1 接口、格式及已有历史保持原样。

## 发行端

在 `lake.release.parts` 提供 `export_station_part(db, part_id, station, *, attest)`。`part_id` 是已发行的 V1 原件号，`station` 是该件内有原行的站点。原件不存在抛 `HistoryNotFound`。站点参数非法或该站在原件中无行时抛 `ValueError`。发行端对同一原件、同一站点及同一可信配置重导时返回相同编号及内容。已经发出撤回件的原件仍可从发行档案重导，镜像按当地实际办理的撤回结算。

返回可 JSON 往返的字典，包含 `kind`（固定为 `station_part`）、`station_part_id`、`part_id`、`publication_id`、`position`、`station`、`rows` 和 `proof`。`station_part_id` 为独立办理号，与原整件号以及同一原件的其他站件号不同。`position` 沿用 V1 原件的分件位置。`rows` 按原件行序排列，每项为 `{"ordinal": 原件内从零计的行位置, "fact": V1 原行}`。`fact` 沿用 V1 的 `fact_id`、`station`、`litres` 和 `origin`，包括原来的整升文本及出处。站件的任何字段均不得携带其他站的原行正文。

调用方在源端配置 `attest(payload: bytes) -> str`，在镜像预配相应的 `verify(payload: bytes, token: str) -> bool`。同一配置下，`attest` 对相同字节返回相同标记。镜像通过独立配置信任 `verify`，验证时无需连接源库。`proof` 的 JSON 结构及交给可信端口的字节内容由实现决定。提供的 `examples.station_case.make_trust()` 可在示例中模拟该端口。

## 镜像

用 `lake.mirror.acceptance.accept(db, station_part, verify=verify)` 办理上述字典。旧调用继续接收原整件和撤回件，保留原来的对象与 JSON 接口。站件的依据必须足以在断源时确认本站原位齐全、原行及出处真实，并能把整个原件绑定到该次交付。

- 若先收站件，后到的 V1 整件必须符合已核验的整个原件。只检查两件重合的行不足以办理补齐。
- 若先收 V1 整件，后到站件也须与该已收整件核对整个原件的身份。仅使用 V1 的镜像沿用原有接纳规则。
- 办理匹配的站件或原整件时，首次有效到件各发自己的首执。即使事实早已由另一发布入账，也须为这次交付登记原发布下的实收依据。事实号相同只计一行。分站都收齐以后，如果原整件尚未办理，仍可正式办理原整件，实际新增为空。
- 站件成功返回 `AcceptanceResult`，状态为 `received`，首执号为 `station_part_id`。首执 `details` 提供 `part_id`、`station`、与 `facts` 顺序对应的 `ordinals`、沿用 V1 形状的 `facts`，以及 `added_fact_ids`。新增标识按来件行序列出，表示本次实际新增到现账的事实。`origins` 沿用 V1 形状。V1 原整件首执保留原形状及全件原行序。
- 同号同内容重投领原结果。按各自办理号调用 `replay`，重开后仍能取得固定的首执及出处。缺证、坏证、内容冲突或同号异件抛 `ValueError` 或其子类。沿用 `fail_before_commit=True` 检查回滚。办件依据、站账和首执一同提交。
- 撤回原发布时，只有失去所有有效实收依据的事实退出。撤回后首次收到的有效站件或整件返回 `late`，无成功首执。已经办理的首执仍可复领。

## 样例与运行

`python3 -B -m examples.station_case` 可运行 V1 对照。夹具的 `build_source(db)` 返回 P 的原整件、重叠发布 Q 的原整件和 P 的撤回件。P 依次是北闸 A=7 L、南堤 B=11 L。`extra_north=True` 时再添北闸 C=7 L，本站位置为 0 和 2。`changed_origin(part, ordinal)` 生成同号同值异出处的对照件。镜像可沿用已有提交中断开关。

新增业务核验须覆盖实际站件发行和离线入账、站件或整件补齐、整件先到、篡改拒绝、重投重开、撤回和失败后的重试。断源演示从镜像读取北闸先入 7 L、南堤后补 11 L 的账面，并按号读取原首执。

沿用根目录 `.pointwise-runtime.json`。`version` 为 1，`kind` 为 `cli`，`setup` 为准备命令参数数组的列表。更新 `verify` 和 `demo` 两条命令的参数数组以运行本次业务核验和演示。核验继续执行 `check_project.py` 的原套件，并在任一核验失败时非零退出。
