# FolderPilot 项目状态

更新：2026-10-23（Asia/Singapore），版本 0.1.0。

## 已实现

- 文件扫描、四种名称/路径匹配、SHA-256 比较、差异报告。
- 安全补全、镜像同步、规则清理、统一校验执行、隔离与恢复。
- 中文 Tkinter 七页界面、后台任务、取消、任务配置与日志。
- Windows 单文件构建、实际 EXE 自检、GitHub Actions Windows 测试及标签发布配置。
- 首次使用引导：明确源和目标、三步按钮、同步模式一句话区别、简化界面技术提示。
- Windows DPI manifest 与窗口创建前 DPI 适配，字体、窗口和表格尺寸随缩放调整。

## 验证

最终源码自动化测试 58 项全部通过，0 失败、0 跳过；包含后台界面与 DPI 尺寸验证。
源码实际启动七个页面与文件操作自检通过，当前实际屏幕为 144 DPI（150%）。
改版单文件 EXE 已在 Windows 11 x64 上构建并实际启动自检通过，大小 13,759,391 字节。
自检记录每显示器 DPI 感知、144 DPI、Tk scaling 约 2.0、导航宽度 270 像素。
本地 EXE SHA-256：`a9dc77225b08f8d4628baf112ece91ba0169d93b893d4cc853db483037fa74c3`。
本地与 GitHub Runner 构建的二进制可能因环境不同而不同；以各自产物的 SHA256SUMS.txt 为准。

## 发布

用户已选择公开仓库、MIT 许可证、GitHub 账号 `Galt5-0000`。
本机 Git 凭据已核验该账号授权有效，具有 repo 与 workflow 权限。
公开仓库已创建：https://github.com/Galt5-0000/FolderPilot 。
源代码与 `v0.1.0` 标签已推送，发布代码提交：`44a460f7cc6a896c042762895fbec87621ccc339`。

- Windows CI：[实际成功的工作流](https://github.com/Galt5-0000/FolderPilot/actions/runs/39924952474)。
- Runner：Windows Server 2025 x64、Python 3.13.16，58 项测试通过，0 失败、0 错误、0 跳过。
- CI 内实际构建并启动 EXE 自检通过。下载该 CI 产物后在本机 Windows 11、150% 缩放下实际启动自检再次通过。
- [正式 Release v0.1.0](https://github.com/Galt5-0000/FolderPilot/releases/tag/v0.1.0)，非草稿、非预发布。
- [Windows EXE](https://github.com/Galt5-0000/FolderPilot/releases/download/v0.1.0/FolderPilot.exe)，12,879,322 字节，公开下载 HTTP 200。
- Release EXE SHA-256：`9dc1737a4b4aff5923f82f0126ba63003daf1bad8c69a30618dad1202b2ed639`。
- 附件已核验：EXE、SHA256SUMS.txt、build-info.json、smoke-result.json、USER_GUIDE.md、test-results.xml。
- [源码 ZIP](https://github.com/Galt5-0000/FolderPilot/archive/refs/tags/v0.1.0.zip)；也可 `git clone https://github.com/Galt5-0000/FolderPilot.git`。

首次分支与标签一起推送后，本次只观察到 main 分支构建，未出现独立标签构建。首版通过 GitHub API 发布了同一标签提交对应的 Windows CI 构建附件，没有替换或覆盖已有发布。工作流保留后续标签自动发布配置。

本地 `dist/FolderPilot.exe` 是本机 Conda 环境构建；发布附件是 Windows Runner 构建。二者来自相同功能代码、均通过实际启动自检，各自使用配套校验和。

## 尚未完成与限制

本次功能实现、测试、Windows 打包、源代码推送及正式发布均已完成。
窗口人工检查在用户按 Escape 后停止；未继续桌面自动操作。DPI 模式通过实际 EXE 自检验证，100%/200% 尺寸通过测试验证，未声称所有显示器组合均完成人工视觉验收。
未完成 EXE 代码签名、真实断电/设备故障测试与所有 Windows 版本验证，具体支持边界见 README 和测试报告。

## 开发约束

所有文件在本项目内维护。复用现有 Python 3.13、Tkinter、pytest、PyInstaller，不修改共享环境。
使用 `python scripts/build.py` 完整验证并打包；不更改 PowerShell 执行策略。
测试使用项目内 `.test-tmp/` 的生成数据；本地应用/构建数据在忽略目录 `.local/`。
具体边界与故障恢复说明见 README 和 docs/USER_GUIDE.md。
