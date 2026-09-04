# Video Knowledge

把你主动选择的视频，可靠地转换为可核查、可继续追问、可连接项目的 Markdown 知识资产。

Video Knowledge 是一套面向 Codex 的本地视频处理 Skill。它先在本地完成媒体探测、语音转写和证据帧提取，再根据用户真正想达到的目的，选择以下一种主模式：

当前预览版本见 [VERSION](VERSION)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。升级和回退说明见 [UPGRADING.md](UPGRADING.md)。

- **吸收（Absorb）**：把线性视频重建成可以独立理解的知识；
- **判断（Judge）**：区分事实、主张、证据、推断和仍未验证的内容；
- **应用（Apply）**：把有用内容连接到用户提供的项目、决策或下一步行动。

分析完成后，可以围绕同一份视频资产继续澄清、质疑、扩展或连接其他知识，不需要重新下载和转写。

## 它不是什么

- 不是自动寻找爆款的工具；
- 不是一键仿写或洗稿工具；
- 不承诺解释一条内容为什么必然走红；
- 不会把视频里的说法自动当成事实或永久知识。

## 当前状态

| 能力 | 状态 |
|---|---|
| Windows x64 + Python 3.12 + CPU int8 | 已完成干净环境与单命令安装验证 |
| 本地视频探测、抽帧、转写和 Markdown 输出 | 已验证 |
| 一次确认后的完整安装与失败续跑 | 已验证 |
| 公共视频链接获取 | 取决于站点、现有下载器或可选适配器 |
| macOS | 架构上预留，尚无真机验证，不宣称支持 |
| 自动说话人分离 | 尚未实现；多人内容使用保守的上下文校正 |

## 安装

最简单的方式是把本仓库链接交给 Codex，并发送：

> 请安装这个仓库里的 Video Knowledge。先给我只读安装计划；涉及下载模型、安装系统组件或选择存储位置时集中说明，等我确认后再执行完整安装并用 Doctor 验收。

Codex 的官方文档说明，`$skill-installer` 可以从其他仓库下载 Skill。独立 Skill 适合本地安装和试用；更广泛的正式分发后续应考虑 Plugin：<https://developers.openai.com/codex/build-skills>

完整安装边界见 [安装契约](video-knowledge/references/install-contract.md)；结构化失败和平台适配见 [修复协议](video-knowledge/references/remediation-protocol.md)。

手动检查时，在仓库根目录运行：

```text
python video-knowledge/scripts/setup.py --plan
```

确认计划中的路径、下载和系统变更后：

```text
python video-knowledge/scripts/setup.py --apply --yes
```

安装器会依次完成运行环境、固定模型、FFmpeg、Skill 安装和最终 Verify。中途失败时会保留已经验证的部分；修复后重新运行同一条命令即可续跑。

### macOS 预检（只读）

当前 macOS 不能执行 `--apply`。Apple Silicon 测试者可先运行：

```text
python3 video-knowledge/scripts/macos_preflight.py --workspace /absolute/workspace
```

该命令不安装任何软件，不下载模型，不改动系统。请先提交 JSON 报告，再决定是否进入平台适配。

## 第一次使用

发送本地视频或可以访问的公开视频链接，并用一句话说明目的，例如：

```text
请分析这个视频。我主要想判断主角的经历是否可信，并区分已经验证、只有口述和目前无法确认的部分。
```

如果目的不明确，Skill 只会做一次简短选择：吸收、判断或应用。正式输出默认包括精简主文、完整证据底稿、时间轴转写和证据帧。

更多不含第三方视频内容的请求示例见 [examples/README.md](examples/README.md)。

## 数据与隐私

媒体探测、抽帧和语音转写由本项目脚本在本机执行；模型和依赖需要从其官方来源下载。最终分析由运行 Skill 的 Codex／ChatGPT 环境完成，因此交给宿主模型的文字、画面和提示词适用相应产品的数据规则。处理私人或敏感素材前，请先阅读 [PRIVACY.md](PRIVACY.md)。

本仓库不包含模型权重、FFmpeg 二进制、视频、转写结果、Cookie、账号凭据或 API 密钥。

## 第三方组件

项目代码采用 MIT License。运行时会使用或下载 Faster-Whisper、CTranslate2、Hugging Face Hub、Systran Faster-Whisper Small 模型以及 FFmpeg。来源与许可证边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 作者与协作

由 [Running-Tomato-A](https://github.com/Running-Tomato-A) 创建并维护，与 [OpenAI Codex](https://developers.openai.com/codex/) 协作完成产品设计、Skill 流程、实现、测试和发布。

## 许可证

见 [LICENSE](LICENSE)。
