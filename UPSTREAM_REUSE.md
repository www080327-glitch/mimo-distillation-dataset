# 上游数据复用矩阵

检查日期：2026-11-09。只取少量样本，所有上游正文、代码、截图和适配输出都留在本地。下表是接入和许可记录，不是训练样本筛选标签。转换计入上游复用，MiMo 新增蒸馏产量为 **0**。

| 上游、修订和范围 | 结论 | 实际检查与下一步 |
| --- | --- | --- |
| [WebUniverse-Mix](https://huggingface.co/datasets/WebUniverse-NSL/WebUniverse-Mix/tree/f3f0bfd16cb1fec65b40ee50ef93c0162c01bac8) · `f3f0bfd16cb1fec65b40ee50ef93c0162c01bac8` · `train` | **BLOCKED：需接受访问条件** | 公共目录列出 `data/train-00000.parquet`；匿名检查返回 HTTP 401，0 条样本。上游说明有有序 `messages`（含 `role/content/loss`）、`images`（字节与路径）、`tools`、`system`、任务 ID 及 `trajectory_model`。获准后先核查少量 ID、原监督掩码、图像顺序、模型和来源条款。 |
| [WebUniverse-Env](https://huggingface.co/datasets/WebUniverse-NSL/WebUniverse-Env/tree/73fb5c769e43d91720a913828f655e6d95fa553f) · `73fb5c769e43d91720a913828f655e6d95fa553f` · Harbor 环境索引 | **BLOCKED：需接受访问条件** | 公共目录确认有 `archives/000/webuniverse-00017.tar.gz`；该包、`index.jsonl`、`prepare.py` 的匿名访问均为 HTTP 401，0 个环境。按文档，同 ID 连到 Mix；包包含 `task.toml`、初始项目和 Dockerfile、验证器、元数据和文件哈希。获准后用上游 `prepare.py --id webuniverse-00017` 准备单个环境；Linux/amd64 Docker 与运行时镜像此次 **NOT_RUN**。 |
| [WebGen-Agent SFT](https://huggingface.co/datasets/luzimu/webgen-agent_train_sft/tree/b8ffb7fcd9b633e9bdf2f4d47b692a15a58ca2bd) · `b8ffb7fcd9b633e9bdf2f4d47b692a15a58ca2bd` · `train` · MIT（数据卡） | **需格式适配；视觉回放 BLOCKED** | 固定修订 JSONL 的前 3 条：`train_000042/step10.json`（13 消息、19 个文件标记）、`train_000066/step6.json`（15、17）、`train_000072/step8.json`（19、21）。交错 user/assistant，实见 Bolt 文件、启动、shell、结束及 `screenshot_validated` 标记。样本消息正文均为字符串，无图像字段或可解析的历史截图引用；仓库的 `fig/` 是论文插图。适配器提供文本顺序和动作索引；不把标记当独立工具返回或截图。 |
| [WebSight](https://huggingface.co/datasets/HuggingFaceM4/WebSight/tree/b11f8172f89c992b56ac702319e02c428cca4a4e) · `b11f8172f89c992b56ac702319e02c428cca4a4e` · `v0.2/train` · CC BY 4.0（数据卡） | **可直接复用：静态图文/页面素材** | 查看器样本 `v0.2/train:0,1,2` 的 `image/text/llm_generated_idea` 均可读；实际获取和解码 3 张 2560×1440 JPEG，HTML 分别 1274、2135、2253 字符。样本 HTML 引用外部样式；仅作为静态材料读取，无历史操作序列。直接使用上游数据加载器、保留署名和版本；本次不额外适配，也不运行 HTML。 |
| [FineVision](https://huggingface.co/datasets/HuggingFaceM4/FineVision/tree/3c380a731a3429c1d04693d6ec16d7e683def84c) · `3c380a731a3429c1d04693d6ec16d7e683def84c` · `websight/train` | **可直接复用：图文格式；其它子集许可待确认** | 实读 `websight/train:0,1`，两条均为 `source=websight`，各 1 张实际解码的 2048×1152 图、1 对图文消息，并附既有评分字段。上游不提供全库统一许可；WebSight 原素材依据其 CC BY 4.0，FineVision 对其有权许可的提示使用 CC BY 4.0。只登记这个子集，不推及其他配置，也不把上游评分作本项目训练信号。同源素材按源数据去重，不把原 WebSight 和重包视为独立增量。 |
| [SWE-smith trajectories](https://huggingface.co/datasets/SWE-bench/SWE-smith-trajectories/tree/08e109b4a59eaeebf80e4675cd125d42e7ac99a4) · `08e109b4a59eaeebf80e4675cd125d42e7ac99a4` · `tool` · MIT（数据卡） | **需格式适配；文本工具轨迹已跑通** | 从固定 Parquet 分片首个行组实际取 2 行。Django Money 样本 49 条消息、24 个动作、23 条工具返回，23 个返回 ID 与调用对应；apispec 样本 43、21、20，20 个对应。前者 patch 字段为空，后者非空；`resolved` 是上游记录。两条均无历史截图。只验证记录形状，不运行命令、构建仓库或验证补丁；基底项目环境和各仓库许可须分别核对。 |
| [DesignBench](https://github.com/WebPAI/DesignBench)、[FronTalk](https://github.com/shirley-wu/frontalk)、本项目冻结测试 | **EVAL_ONLY** | 仅登记；未拉取、未适配、未导出到训练数据池。 |

WebUniverse 公共资料描述 **15,000 对轨迹和任务环境**，其中包含迭代开发。不能再把「有环境的前端迭代数据」视作空白。[Mix 许可](https://huggingface.co/datasets/WebUniverse-NSL/WebUniverse-Mix/blob/f3f0bfd16cb1fec65b40ee50ef93c0162c01bac8/LICENSE.md)和 [Env 许可](https://huggingface.co/datasets/WebUniverse-NSL/WebUniverse-Env/blob/73fb5c769e43d91720a913828f655e6d95fa553f/LICENSE.md)正文均已读到：CC BY 4.0 仅覆盖发布者有权许可的部分，第三方网站、截图和源码保留原权利，模型生成材料另受适用的提供方条款约束。本次未接受访问条件。可下载和可复用均不等于可重新公开转载。

## 本地适配和样本定位

`upstream_samples.py` 只处理从相应固定修订取来的本地 JSONL。输出保留 `upstream_source`、`revision`、`split`、`license`、`sample_id`、`input_row` 和 `conversion`，标记 `LOCAL_INSPECTION_ONLY`，没有训练池入口。适配不执行代码，不生成反馈，也不补造缺失的媒体或环境。

```sh
# 流式读前 3 行，不落整份源文件。
curl -fsSL 'https://huggingface.co/datasets/luzimu/webgen-agent_train_sft/resolve/b8ffb7fcd9b633e9bdf2f4d47b692a15a58ca2bd/webgen-agent_train_sft.jsonl' \
  | head -n 3 > webgen-source.jsonl
python3 upstream_samples.py webgen webgen-source.jsonl --out webgen-local.jsonl
```

SWE-smith 取固定修订 `tool` 分片 `data/tool-00000-of-00008.parquet` 前两行。用已有的 Hugging Face Datasets 环境可按下例流式读取；底层 Parquet 读取可能需要首行组的列字节。本次通过 HTTP Range 读取约 30 MiB，未下载整分片。无现成环境时，可直接在上游 [tool 查看器](https://huggingface.co/datasets/SWE-bench/SWE-smith-trajectories/viewer/default/tool) 定位这两个 ID；查看器有截断的行，不应用作完整轨迹。

```python
from itertools import islice
import json
from datasets import load_dataset

rows = load_dataset("SWE-bench/SWE-smith-trajectories",
    revision="08e109b4a59eaeebf80e4675cd125d42e7ac99a4",
    split="tool", streaming=True)
with open("swe-source.jsonl", "w", encoding="utf-8") as file:
    for row in islice(rows, 2):
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
```

```sh
python3 upstream_samples.py swe-smith swe-source.jsonl --limit 2 --out swe-local.jsonl
```

样本稳定定位：

- SWE-smith：`django-money__django-money.835c1ab8.func_pm_ctrl_shuffle__viqnyl9u.8qa84d2e`、`marshmallow-code__apispec.8b421526.func_pm_remove_assign__kdkrbg6a.8qa84d2e`。
- [WebSight v0.2/train](https://huggingface.co/datasets/HuggingFaceM4/WebSight/viewer/v0.2/train)：查看器行号 0–2；JPEG SHA-256 前缀依次为 `3049c7aae08b`、`690c1e31222b`、`070262eb0188`。直接读取 `image` 和 `text`；不保存会过期的查看器签名 URL。
- [FineVision websight/train](https://huggingface.co/datasets/HuggingFaceM4/FineVision/viewer/websight/train)：查看器行号 0–1；实际 JPEG SHA-256 前缀 `e8d507b56023`、`d1c0c83670c2`。读取 `images` 和 `texts`，保留 `source` 和子集许可。
