# FolderPilot

简体中文 Windows 桌面工具，用于通用文件夹差异检测、安全补全/镜像同步、按规则清理及隔离恢复。当前版本 **0.1.0**，MIT 许可证。

[下载 Windows EXE](https://github.com/Galt5-0000/FolderPilot/releases/download/v0.1.0/FolderPilot.exe) · [正式发布](https://github.com/Galt5-0000/FolderPilot/releases/tag/v0.1.0) · [源代码 ZIP](https://github.com/Galt5-0000/FolderPilot/archive/refs/tags/v0.1.0.zip)

## 使用

下载 Release 中的 `FolderPilot.exe`，双击即可，无需安装 Python。完整步骤见 [中文使用说明](docs/USER_GUIDE.md)。本地构建产物位于 `dist/`。

界面按“选文件夹 → 扫描 → 确认”引导。同步页直接标注：**安全补全保留目标独有文件；镜像同步会将它们移入隔离区。** 支持 Windows 高 DPI 显示，字体和控件按屏幕缩放调整。

- **差异检测**：相对路径对应、SHA-256 精确比较（默认）、快速比较、文件/目录差异、移动线索、分类筛选和报告导出。
- **文件夹同步**：安全补全保留目标独有内容；镜像清理主动启用并二次确认；覆盖旧版本先隔离。
- **规则清理**：文件名、文件名主体、相对路径、相对路径忽略扩展名四种策略；可设置扩展名、递归和大小写。
- **隔离与恢复**：复制校验后清理、恢复冲突检查、覆盖前保存当前版本；永久删除单独二次确认。
- **任务与日志**：版本化 JSON、后台处理及取消、准确记录部分完成和失败、识别中断任务并阻止重放。

匹配、比较与执行分别实现：按文件名主体匹配时，内容与 SHA-256 不参与对应关系判断。同步则按相对路径对应，再比较内容。

## 安全边界

所有业务文件修改通过统一引擎：完整计划预览、确认令牌绑定计划、执行前重新扫描、逐文件复核、临时复制与 SHA-256 校验、旧版本隔离、SQLite 持久记录。禁止同目录、相互嵌套、磁盘根目录、链接/联接点、不完整扫描和未解决的高风险歧义。隔离存储必须独立于业务目录。

隔离区不会自动清空，也不是完整备份系统。不提供完整事务回滚；中断后人工核查，再重新生成计划。不要让其他程序或使用不同隔离位置的多个实例同时修改相同目录。

## 源码运行和开发

Python **3.11+**（实际验证 3.13.12），Tkinter 必须可用，运行时不依赖第三方库。

```powershell
python -m folderpilot
# 也可选择独立的应用数据目录
python -m folderpilot --data-dir .local/app-data
```

应用数据默认在 `%LOCALAPPDATA%\FolderPilot`，不写入源码或 EXE 解包资源目录。源代码与打包版本均直接包含 Python 模块，无需外部资源文件路径。

复用可用解释器及工具；如缺依赖，应在项目内独立环境安装，避免更改共享环境：

```powershell
conda env create --prefix .conda-env --file environment.yml
conda run --prefix .conda-env python -m folderpilot
# 或在已有项目独立环境中
python -m pip install -r requirements-dev.txt
```

## 测试与打包

```powershell
python -m pytest -q --junitxml=test-results.xml
python -m folderpilot --smoke-test .local/source-smoke.json
python scripts/build.py
# 允许执行本地 PowerShell 脚本的环境也可运行
./scripts/build.ps1
```

打包前运行全部 pytest；PyInstaller 生成 `dist/FolderPilot.exe` 单文件 GUI 程序。随后实际启动 EXE，创建和刷新七个界面，并使用生成的临时文件执行同步、清理和恢复。生成 `SHA256SUMS.txt`、`build-info.json` 和 `smoke-result.json`，任何失败均停止构建。不修改 PowerShell 执行策略。

自动化测试只使用临时数据；权限/磁盘不足/损坏/复制失败等部分场景通过故障注入测试。详细结果与限制见 [测试报告](docs/TEST_REPORT.md)，当前交付状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 项目结构

```text
folderpilot/
  models.py       数据模型与异常
  safety.py       路径边界与链接检查
  scan.py         只读扫描
  matching.py     名称/路径匹配索引
  compare.py      元数据、SHA-256 与内容比较
  planning.py     差异报告、同步/清理计划
  engine.py       统一校验执行、隔离与恢复
  storage.py      SQLite 日志、隔离目录、执行锁
  config.py       任务格式与版本校验
  ui.py           中文 Tkinter 界面与后台任务桥接
  smoke.py        源码/打包程序自检
tests/            自动化测试
scripts/          Windows 打包、版本资源、校验信息
.github/workflows/windows.yml
docs/             中文说明、测试报告、发布说明
```

## GitHub Actions 和发布

`main` 分支推送、PR、手动执行均在 `windows-latest` 上测试并打包；构建产物上传为 `FolderPilot-Windows-x64`。仅推送 `v*` 标签时，独立 Release 作业获得 `contents: write`，发布 EXE、校验和、自检与测试结果。其他作业只读，不保存任何 Token。已存在 Release 会拒绝覆盖。

确认版本无冲突、更新版本号/版本资源/变更记录，再推送分支及对应标签即可。首版标签 `v0.1.0` 必须与 Python 包版本匹配。仓库地址、正式 Release 和实际远程验证结果以 `PROJECT_STATUS.md` 中的记录为准，不将工作流配置视为已经远程运行成功。

## 已知限制

- 支持范围为 Windows x64 本地普通文件/目录；EXE 未签名。未逐一验证 Windows 所有版本与网络共享。
- 不保证保留 ACL、所有者、NTFS 备用流、加密/压缩/稀疏属性或硬链接关系。
- 快速比较不能证明内容相同；可执行计划强制精确基线，因此大目录会多次读取文件。
- 不自动重命名、不双向同步、不自动解决文件/目录类型冲突和大小写碰撞。
- 规则清理遇到重复键即阻止操作，需改规则或缩小范围；不会自动合并或任意选择重复项。
- 同步选择“跳过冲突”时即使启用镜像，也可能保留不同内容。
- 源端独有和目标缺失在报告中合并为同一分类。大报告保存在内存并显示在 Treeview，极大目录性能尚未调优。
- 无法保证抵御恶意进程的路径抢占与真实断电/存储故障；校验与文件系统替换之间仍有很短的并发窗口。
- SQLite 日志保留完整路径；不上传本机日志或任务配置到仓库。跨卷逻辑采用复制校验后清理，真实跨卷设备故障尚未验证。

## 官方参考

打包参数参考 [PyInstaller 使用文档](https://pyinstaller.org/en/stable/usage.html) 和 [运行时资源路径](https://pyinstaller.org/en/stable/runtime-information.html)。Windows 自动化参考 [GitHub Python 构建与测试](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)。
