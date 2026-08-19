<!-- prompt: 导演语法用 tiktok_drama action=suggest_coverage。只生成覆盖建议（前3秒钩子、景别节奏、对白切反应镜），禁止改 kind/size，禁止 lock。一集最多 2 条 reaction。人在工作台采纳、忽略或锁定类型。 -->
# drama-director

人是导演，Agent 是摄制组。覆盖建议写进 `shots.json` 的 `coverage`，**不要直接改镜头，不要加锁**。

## 何时调用

分镜已 `parse_shots` / 工作台能看到 Shot 列表之后，用：

`tiktok_drama action=suggest_coverage slug=… episode=…`

然后停下来，把建议摘要给用户，请他们在漫剧工作台点 **采纳 / 忽略 / 锁定类型**。

## 规则

1. **前 3 秒必须有钩子**（冲突 / 悬念 / 反差）。慢热定场要提示改 Shot 1 画面，不要替人改词。
2. **景别要有节奏**。连续三镜同一景别（尤其全是 CU）时，建议中间镜换一档。
3. **对白后切反应镜**。连续对白可建议下一镜改为 `reaction` CU；**一集最多建议 2 条 reaction**。
4. 已锁 `kind` 或整镜 `shot` 的镜头不要再建议覆盖。
5. 禁止调用 lock_shot / patch 来「帮用户锁上」。锁是人的权力。

## 不要做

- 不要插入新 Shot（Q5 只建议改现有镜的 kind/size/画面提示）。
- 不要把 reaction 建议当成已采用。
- 不要改 `agent/loop.py`。
