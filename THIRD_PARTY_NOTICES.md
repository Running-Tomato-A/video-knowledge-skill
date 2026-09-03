# Third-party notices

Video Knowledge 的仓库不重新分发下列模型、Python 包或 FFmpeg 二进制。安装器只记录固定来源、下载所需组件并在本地校验；每个组件仍受其自己的许可证约束。

## Direct runtime components

| Component | Purpose | Source | Upstream license |
|---|---|---|---|
| Faster-Whisper 1.2.1 | Local speech transcription | <https://github.com/SYSTRAN/faster-whisper> | MIT |
| CTranslate2 | Inference engine used by Faster-Whisper | <https://github.com/OpenNMT/CTranslate2> | MIT |
| Hugging Face Hub 1.26.0 | Pinned model download | <https://github.com/huggingface/huggingface_hub> | Apache-2.0 |
| Systran/faster-whisper-small | Local Whisper Small weights in CTranslate2 format | <https://huggingface.co/Systran/faster-whisper-small> | MIT, as declared by the model repository |
| FFmpeg／FFprobe | Media probing and frame extraction | <https://ffmpeg.org/> | LGPL-2.1-or-later by default; some builds or optional components are GPL-2.0-or-later |

FFmpeg 官方说明：基础项目主要采用 LGPL 2.1 或更高版本；启用特定 GPL 组件后，具体构建会适用 GPL。用户应查看实际安装的 FFmpeg 构建配置和随附许可证：<https://ffmpeg.org/legal.html>

## Transitive Python dependencies

`video-knowledge/requirements-windows-py312.lock` 是在 Windows x64／Python 3.12 干净环境中生成的可复现版本清单。锁文件中的传递依赖由各自上游项目授权，并不会因为本仓库采用 MIT License 而改变许可证。

25个锁定版本的PyPI元数据快照见 [DEPENDENCY_LICENSES.md](DEPENDENCY_LICENSES.md)。其中PyPI缺少明确字段的`fsspec 2026.7.0`已按其上游仓库的BSD-3-Clause声明人工复核并在生成脚本中记录覆盖依据。

这些Windows wheel同时在`requirements-windows-py312.lock`中固定SHA-256，安装器强制pip `--require-hashes`。锁定版本的当前OSV已知漏洞查询见 [DEPENDENCY_VULNERABILITIES.md](DEPENDENCY_VULNERABILITIES.md)。漏洞查询是时间点快照，不等于未来无漏洞。

发布前和升级锁文件后，应重新生成依赖许可证报告并检查不兼容或需要额外通知的条款。当前仓库不把第三方代码复制进项目源码。

## No endorsement

上游项目名称仅用于说明依赖关系，不表示其作者认可或维护 Video Knowledge。Video Knowledge 不是 OpenAI、SYSTRAN、Hugging Face、OpenNMT 或 FFmpeg 的官方产品。
