# MiMo 蒸馏数据集

这是独立整理的教师模仿候选数据。文本、示例代码和部分页面为 **AI 生成**，可能有错误或未完成，不能视作真值、人工审核结论或模型能力证明。没有包含模型权重。

从 [GitHub Releases](../../releases) 下载分片。每个版本说明列出实际包含的文件与条数。文件校验：

```sh
shasum -a 256 -c SHA256SUMS
```

对于名称末尾带 `.part-001`、`.part-002` 的文件，下载对应的所有部分和
`MANIFEST.json`，再用 `python3 reassemble_media.py MANIFEST.json --out restored`
按清单拼回逻辑文件。省略 `--out` 只做校验；该脚本不解包、不执行任何数据。

| 分片 | 内容 |
| --- | --- |
| `mimo-text-*.jsonl.gz` | 对话、数学、代码和完整或按状态标注的 HTML 候选；HTML 只是字符串，预览应使用隔离环境。 |
| `mimo-vision-*.jsonl.gz` | 图文描述与视觉问答；按记录中的路径和分片名关联媒体。 |
| `mimo-episodes-*.jsonl.gz` | 前端、长程和工具轨迹；保留可见模型输出和真实工具结果，失败与未完成按状态区分。 |
| `mimo-*-media-*.tar`、`mimo-media-*.tar` | 按内容哈希命名的 PNG，保留原始分辨率与教师视图的区别；容器元数据已剥离。 |

每个版本对应一个数据快照。

本项目原创汇编及可授权贡献采用 [Apache License 2.0](LICENSE)，详见 [NOTICE](NOTICE)。第三方媒体依各记录的来源许可和署名（例如公共领域或 CC0），不改为 Apache 2.0。该许可不扩展任何上游权利，也不声称自动生成内容一定享有著作权。

## English

An independent dataset of candidate teacher imitation examples.
Download versioned shards and checksums from [Releases](../../releases). Outputs are
AI-generated and may be incorrect or incomplete. Third-party media retain their
original rights and credits. See [NOTICE](NOTICE). No model weights are included.
