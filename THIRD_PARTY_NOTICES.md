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
| Playwright 1.62.0 | Control one isolated system Chromium session for direct Douyin acquisition | <https://github.com/microsoft/playwright-python> | Apache-2.0 |

FFmpeg 官方说明：基础项目主要采用 LGPL 2.1 或更高版本；启用特定 GPL 组件后，具体构建会适用 GPL。用户应查看实际安装的 FFmpeg 构建配置和随附许可证：<https://ffmpeg.org/legal.html>

## Transitive Python dependencies

`video-knowledge/requirements-windows-py312.lock` 与 `video-knowledge/requirements-runtime-macos-arm64-py312.lock` 分别固定经过验证的 Windows x64 和 macOS arm64／Python 3.12 运行时。锁文件中的传递依赖由各自上游项目授权，并不会因为本仓库采用 MIT License 而改变许可证。

两套运行时锁中所有精确包版本的 PyPI 元数据快照见 [DEPENDENCY_LICENSES.md](DEPENDENCY_LICENSES.md)。其中 PyPI 缺少明确字段的 `fsspec 2026.7.0` 已按其上游仓库的 BSD-3-Clause 声明人工复核并在生成脚本中记录覆盖依据。

直接采集环境使用单独的 Windows x64 与 macOS arm64 Python 3.12 锁，均包含 Playwright、greenlet、pyee 和 typing-extensions 四个精确版本及各自平台 wheel 的 SHA-256。其 PyPI 许可证元数据快照见 [ACQUISITION_DEPENDENCY_LICENSES.md](ACQUISITION_DEPENDENCY_LICENSES.md)。Setup 只安装 Python 驱动并复用系统浏览器，不重新分发或自动下载 Playwright 浏览器二进制。

所有经过验证的平台锁都固定兼容 wheel 的 SHA-256，安装器强制 pip `--require-hashes`。锁定版本的当前 OSV 已知漏洞查询见 [DEPENDENCY_VULNERABILITIES.md](DEPENDENCY_VULNERABILITIES.md)。漏洞查询是时间点快照，不等于未来无漏洞。

发布前和升级锁文件后，应重新生成依赖许可证报告并检查不兼容或需要额外通知的条款。当前仓库不把第三方代码复制进项目源码。

## No endorsement

上游项目名称仅用于说明依赖关系，不表示其作者认可或维护 Video Knowledge。Video Knowledge 不是 OpenAI、SYSTRAN、Hugging Face、OpenNMT 或 FFmpeg 的官方产品。
