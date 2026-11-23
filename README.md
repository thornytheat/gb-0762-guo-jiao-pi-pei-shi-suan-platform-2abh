# 果胶批配试算台

原料工程师可检查化验单、核算干物、验现有配方、按离散称量寻优并留档。首页展示配方余量轨。顶部横向工序和左侧导航可直达各环节。来料争议样本包含互相矛盾的化验记录与不可试配的原提案。

`docker compose up --build` 后访问 `http://localhost:18461/`。本地安装 `pip install -r requirements.txt` 后，执行 `python -m flask --app app.main run --port=18461`，使用 `pytest -q` 验收。`PECTIN_ARCHIVE` 是归档目录，Compose 将它保存在命名卷中。停用台账默认写 `<PECTIN_ARCHIVE>/qc/holds.jsonl`，可用 `PECTIN_HOLD_ARCHIVE` 单独指定。

停用/解封单经 `POST /api/holds` 登记（同单据号重试不重复登记），新试算自动排除批号精确命中停用单的原料；留档试配的签发资格由 `POST /api/issuance/<id>` 随实际领用按当前台账重判，批号查不清的旧领料单按供应商嫌疑或人工追溯处理，不予自动放行。规则见 [数据定义](docs/DATA-DICTIONARY.md) 的「来料停用台账」。

预览和留档 API 接收 `{"sample":"dirty"}`、`{"sample":"clean"}` 或 `{ "assays":"CSV", "plan":{...}, "proposal":{"批号":2500} }`。计划示例见 `sample_data/dirty/trial.json`。从留档页提交，再到试配签发页审读和下载证据。

- [模块与复算](docs/DEPTH.md)
- [数据定义](docs/DATA-DICTIONARY.md)
