# 电商打包发货监控溯源系统

这是一个 Windows 本地桌面 MVP 程序，用于电商仓库打包发货录像溯源。程序使用 Python 内置 SQLite 作为本地索引数据库，不需要用户单独安装数据库服务，不需要服务器，不联网，不自动删除正式视频。

## 项目结构

```text
packing-monitor/
  main.py
  requirements.txt
  README.md
  config.json
  videos/
  logs/
  app/
    assets/
      app_icon.png
      app_icon.ico
    ui/
      help_dialog.py
      main_window.py
      monitor_tab.py
      query_tab.py
      styles.py
    core/
      recorder.py
      camera.py
      scanner.py
      scanner_guard.py
      file_indexer.py
      database.py
      video_checker.py
      disk_space_checker.py
      video_player.py
      config_manager.py
      logger.py
    utils/
      filename.py
      time_utils.py
      file_utils.py
```

## 核心功能

- 摄像头实时预览和本地 mp4 录制。
- 扫码枪按 USB 键盘输入处理，扫码后回车触发。
- 未录制时扫码开始录制；录制中再次扫描当前相同单号会结束当前录制且不开始新录制；录制中扫描不同单号会结束上一个视频并开始下一个。
- 录制中空扫码或空回车会停止当前录制。
- 如果单号已有历史录制记录，系统会提示重复录制，但不会阻止录制，也不会覆盖旧视频。
- 开始录制、结束录制、切换录制和重复录制时支持语音提示；可选择系统默认语音、自定义语音包或关闭语音。
- 自定义语音包支持上传本地 `wav`、`mp3`、`m4a`、`aac` 音频文件，文件会复制到用户数据目录，不会录入视频文件。
- 录制中预览画面会实时显示单号和时间水印，方便确认最终视频效果；预览水印不影响最终视频水印保存。
- 视频水印写入画面本身：左上角 `单号：XXXXXXX`，左下角秒级日期时间，带半透明黑底。
- 正式视频命名为 `单号_YYYYMMDD_HHMMSS.mp4`，旧格式视频仍可查询和播放。
- 录制完成后自动做视频完整性校验，异常视频只提示和写日志，不自动删除。
- 扫码内容只做清洗、防抖和软提示，不做快递规则校验，不联网，不阻止录制。
- 查询页使用本地 SQLite 文件 `pm_system.db` 保存视频索引、备注、发货/退货类型和重复录制序号；刷新列表时会重新扫描当前查询目录并同步数据库。
- 查询页支持关键词搜索、今天、昨天、最近 7 天、全部日期筛选，并支持分页显示。
- 查询页分页支持每页 10 / 20 / 50 / 100 条、上一页 / 下一页、页码按钮和指定页跳转；搜索、日期筛选、类型筛选会自动刷新分页。
- 设置中可开启百度网盘手动同步；开启并完成授权后，查询页可批量同步未上传视频，也可对未上传或上传失败的视频单条重试，本地视频不会因上传成功或失败被删除。
- 查询页会标记重复录制记录；同一单号存在多条视频时，“文件状态”列会显示“正常”和“重复第 N 次”标签。
- “重复第 N 次”表示该视频是该单号的第几次录制，只有一条记录的单号不会显示重复标签。
- 查询页支持点击视频名称播放、双击行播放、点击路径定位磁盘文件、确认后删除物理视频文件。
- 查询页支持 `Ctrl + C` 复制选中行内容；右键菜单支持复制单元格、复制整行、复制视频路径、打开视频和打开所在文件夹。
- 删除确认弹窗按钮为中文“确认 / 取消”；删除成功或失败会使用左下角状态提示，不再弹出二次确认。
- 主界面右上角提供“使用说明”按钮，以页签形式内置打包录制、视频查询、查询目录、删除视频、基础配置、数据保存和常见问题说明，不需要联网。
- 启动、录制前、录制后检查视频保存盘剩余空间，只提示，不自动清理。
- 成功、失败、警告等短暂操作结果统一使用左下角状态提示显示，不占用页面布局空间；需要确认或输入的操作仍然使用弹窗。
- 日志写入 `logs/app_YYYYMMDD.log`。

## Logo 图标

程序图标资源位于 `app/assets/`：

- `app_icon.png`：正式应用图标 PNG 原图。
- `app_icon.ico`：Windows 窗口图标、任务栏图标、PyInstaller 打包图标和安装包图标。

图标使用监控镜头、包裹和条形码元素，适合仓库打包监控类工具软件。资源为项目内原创文件，不依赖第三方版权图片，也不需要联网下载。

## 使用说明入口

软件主界面右上角提供“? 使用说明”按钮，鼠标悬停会显示“查看软件使用说明”。点击后会打开软件内置说明窗口，按页签查看打包录制、视频查询、查询目录、删除视频、基础配置、数据保存和常见问题说明。

使用说明内容直接内置在程序中，不需要联网，也不会打开网页。打开说明窗口不会停止摄像头预览或当前录制。

## 安装运行

建议在 Windows 10/11 的 Python 3.10+ 环境中运行。

```powershell
cd "E:\PM System"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

如果使用百度网盘同步功能，开发环境必须安装 `requests`。`requests` 已包含在 `requirements.txt` 中，运行 `pip install -r requirements.txt` 后即可使用授权、测试连接和同步上传功能。

如果当前项目路径较长，安装 PySide6 时遇到 Windows 长路径限制，可以把虚拟环境建到更短路径：

```powershell
python -m venv E:\pmvenv
E:\pmvenv\Scripts\activate
cd "E:\PM System"
pip install PySide6 opencv-python Pillow
python main.py
```

首次启动会自动创建 `videos` 和 `logs` 目录。扫码输入框启动后会默认聚焦。

## 配置说明

配置保存于 `config.json`，主要字段：

- `video_save_dir`：视频保存目录，默认 `videos`。
- `current_record_type`：打包监控页当前录制类型，支持 `发货` / `退货`，默认 `发货`。
- `camera_index` / `camera_name`：摄像头索引和系统设备名。
- `resolution`：`original`、`720p`、`1080p`。
- `fps`：帧率使用固定下拉选项：`15 FPS`、`20 FPS`、`25 FPS`、`30 FPS`、`60 FPS`，推荐并默认使用 `25 FPS`。`60 FPS` 画面更顺滑，但文件更大，对摄像头和电脑性能要求更高。
- `recording_max_long_edge`：录制长边上限使用固定下拉选项：`不限制`、`960`、`1280`、`1920`，推荐并默认使用 `1280`；设置为 `0` 表示不限制，使用摄像头原始分辨率。
- `video_format`：默认 `mp4`。
- `auto_continue_recording`：录制中扫描不同单号时是否自动开始下一段。
- `watermark_font_size` / `watermark_margin`：水印字号和边距。
- `scanner_guard`：扫码清洗、防抖和软提示配置，`block_invalid` 默认且必须为 `false`。
- `recording_quality`：短视频提醒阈值，默认小于 3 秒提示。
- `disk_space`：磁盘空间提醒阈值，默认 20GB 警告、10GB 严重警告。
- `voice_prompt`：录制语音提示配置，支持系统默认语音、自定义语音包和关闭语音；自定义音频保存在用户数据目录的 `voice` 子目录中。
- `netdisk_sync`：百度网盘手动同步配置，包含开关、App Key、远程根目录和本机 token 信息；token 不显示在界面中，上传记录状态保存在 SQLite 视频索引中。

基础配置已移动到右上角“设置”入口中。设置窗口包含“基础配置”和“语音提示”页签；“摄像头设备”“分辨率”“帧率”“录制长边上限”“水印字号”“水印边距”旁边都有问号帮助图标，点击后可以查看中文配置说明。正在录制时不建议修改基础配置，请结束录制后再调整。

打包监控页右侧现在主要用于高频打包操作，依次展示录制状态、扫码控制、操作按钮和最近录制。最近录制会显示最近保存成功的 3 条视频，并支持快速打开视频或定位到文件。

## SQLite 本地数据库

程序会自动创建本地 SQLite 数据库文件 `pm_system.db`，用于保存视频索引、视频元数据、备注、发货/退货类型和重复录制序号等信息。SQLite 使用 Python 内置 `sqlite3` 模块，不需要用户安装 MySQL、SQL Server、PostgreSQL 或任何数据库服务。

数据库只保存索引和业务信息，视频文件仍然保存在软件配置的视频保存目录中。开发环境运行时，`pm_system.db` 位于项目目录；安装后运行时，`pm_system.db` 位于用户数据目录，和 `config.json`、`logs`、`videos` 同级，避免安装到 `C:\Program Files` 后出现写入权限问题。

点击“刷新列表”会扫描当前查询目录下的真实视频文件，并把文件大小、时长、分辨率、编码、文件状态等信息同步到 SQLite。SQLite 是本地文件数据库，不联网，不上传数据。

## 视频查询列表

视频查询页面当前列表字段为：序号、单号、录制时间、分辨率/编码、大小/时长、类型、备注、文件状态、场景视频、操作。

- “分辨率/编码”列上下两行展示视频分辨率和编码，数据库字段缺失时会在刷新列表时尝试自动补齐。
- “大小/时长”列上下两行展示视频文件大小和视频时长。
- “类型”列以标签形式显示 `发货` / `退货`，查询列表内只读；新录制视频的类型由打包监控页当前录制类型决定。
- 打包监控页可选择当前录制类型，新录制视频会记录为当前选择的 `发货` 或 `退货`。
- 查询页顶部支持 `全部` / `发货` / `退货` 类型筛选，并可与关键词搜索、日期筛选、查询目录切换组合使用。
- “备注”列无备注时显示“点击添加备注”，点击或双击可编辑备注，备注最多 500 字，只保存到 SQLite。
- “文件状态”列继续显示“正常”，如果同一单号有多条录制记录，会在右侧显示“重复第 N 次”标签，并可通过 tooltip 查看“该单号第 N 次录制，共 M 次”。
- “场景视频”列提供“打开 / 定位”：打开会调用 Windows 默认播放器播放视频，定位会打开资源管理器并尽量选中该视频文件。
- 搜索支持按单号、视频名称和备注模糊搜索；视频名称和完整路径仍保留在索引数据中，用于播放、定位、复制、tooltip 和日志。
- 列表底部支持分页，默认每页 20 条，可选择 10 / 20 / 50 / 100 条/页，支持上一页、下一页、页码按钮、省略号和“前往指定页”跳转；SQLite 数据源下分页使用 `COUNT(*)`、`LIMIT` 和 `OFFSET` 查询，适合后期数据量增大。
- 当前版本不支持面单图片列、不支持自动截图、不支持面单识别。

## 视频查询目录切换

视频查询页面支持修改查询目录：

- 可以直接在“当前查询目录”输入框中输入路径，按 Enter 回车后立即切换并刷新列表。
- 可以点击“选择目录”选择文件夹，选择完成后自动切换并刷新。
- 可以点击“恢复默认”恢复到当前配置的视频保存目录。
- 切换查询目录只影响视频查询页面，不会修改打包监控页面的录制保存目录。
- 切换查询目录只影响当前查询页筛选范围；刷新列表会扫描当前目录，并把该目录中的视频记录同步到 SQLite。
- 刷新列表会递归扫描当前查询目录，兼容根目录旧视频和 `年/月/日` 子目录中新录制的视频。

## 性能建议和语音提示

如果录制视频出现跳帧、卡顿或不连续，优先尝试：

- 将帧率设置为 `25 FPS`。
- 将录制长边上限设置为 `1280`。
- 降低摄像头分辨率。
- 关闭其他占用摄像头、CPU 或磁盘的软件。
- 确认视频保存目录所在磁盘空间充足，并尽量使用写入速度稳定的磁盘。

`60 FPS` 会明显增加电脑压力、磁盘写入压力和视频文件大小，只有摄像头和电脑性能足够时再使用。程序会在日志中每 5 秒记录一次轻量性能指标，包括采集 FPS、目标 FPS、水印耗时、写入耗时、队列长度和丢帧数量；录制结束时会记录总帧数、实际时长和平均录制 FPS。

语音提示不联网，也不会录入视频文件。系统默认语音会优先使用 `pyttsx3`，并保留 Windows SAPI / PowerShell 兜底；自定义语音包会播放用户上传的音频文件。若系统语音仍有延迟，建议缩短提示文字，并确认已安装 `pyttsx3` 和 `pywin32`。语音不可用时只会写日志，不影响录制。

可以不启动完整软件，单独运行语音测试脚本：

```powershell
cd "E:\PM System"
.\.venv\Scripts\python.exe tools\test_voice_prompt.py
```

脚本会播放“语音测试成功”，并打印当前语音引擎、播放提交结果和最近错误信息。

如果出现只有第一次语音会响、第二次之后无声的情况，优先运行上面的脚本做连续播放测试。脚本会连续播放“语音测试一 / 语音测试二 / 语音测试三”，并输出每一次 `speak` 是否成功、语音线程是否仍然存活。若测试脚本也只有第一次响，请查看 `logs` 中 `VoicePrompt`、`pyttsx3 runAndWait`、`worker 取到语音文本` 等日志；若脚本正常但软件内不响，重点检查基础配置页语音开关和运行中的 `VoicePrompt` 实例日志。

## 打包和制作安装包

当前版本：`v1.0.3`。软件可以使用 PyInstaller 打包为 onedir 程序目录，再使用 Inno Setup 制作 Windows 安装包。目标电脑不需要安装 Python，不需要安装 SQLite，也不需要部署任何数据库服务。

安装依赖：

```powershell
cd "E:\PM System"
.\.venv\Scripts\activate
pip install -r requirements.txt
```

打包前建议先做语法检查：

```powershell
python -m compileall main.py app
```

使用项目根目录的 `build.bat` 生成 onedir 程序目录：

```powershell
.\build.bat
```

`build.bat` 内部使用的 PyInstaller 关键参数包括：

```powershell
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "电商打包发货监控溯源系统" --icon "app\assets\app_icon.ico" --add-data "app\assets;app\assets" --hidden-import sqlite3 --hidden-import requests --hidden-import pyttsx3 --hidden-import pyttsx3.drivers --hidden-import pyttsx3.drivers.sapi5 main.py
```

打包完成后，程序位于：

```text
dist\电商打包发货监控溯源系统\电商打包发货监控溯源系统.exe
```

注意：onedir 模式不能只单独拷走 exe 文件运行，必须保留整个 `dist\电商打包发货监控溯源系统\` 目录，否则可能缺少 `_internal\python312.dll`、PySide6、OpenCV 等依赖。

确认 dist 目录中的 exe 可以正常运行后，运行项目根目录的 `build_installer.bat` 生成安装包：

```powershell
.\build_installer.bat
```

脚本会先检查以下文件是否存在：

```text
dist\电商打包发货监控溯源系统\电商打包发货监控溯源系统.exe
```

如果提示“未检测到打包后的 exe”，请先运行 `build.bat`。

`build_installer.bat` 会优先调用当前机器上的 Inno Setup 编译器：

```text
C:\Users\lin\AppData\Local\Programs\Inno Setup 6\ISCC.exe
```

如果该路径不同，可以修改 `build_installer.bat` 中的 ISCC 路径；脚本也会尝试 PATH、`C:\Program Files (x86)\Inno Setup 6\ISCC.exe` 和 `C:\Program Files\Inno Setup 6\ISCC.exe`。如果提示没有 `ISCC.exe`，请检查 Inno Setup 是否安装成功。

安装脚本为：

```text
installer\PMSystem.iss
```

也可以手动打开这个 `.iss` 文件并点击 Compile。最终安装包位置：

```text
installer\output\PMSystem_Setup_v1.0.3.exe
```

安装包界面使用简体中文，支持选择安装位置、创建桌面快捷方式、开始菜单快捷方式、卸载，以及安装完成后立即运行。

默认安装目录为：

```text
C:\Program Files\PMSystem
```

如果在 32 位安装模式或部分系统环境下运行，可能显示为：

```text
C:\Program Files (x86)\PMSystem
```

软件显示名称、桌面快捷方式名称和开始菜单快捷方式名称仍然是：

```text
电商打包发货监控溯源系统
```

如果测试时仍显示旧的中文安装目录，通常是旧版安装记录影响。当前脚本已设置 `UsePreviousAppDir=no`，建议先卸载旧版本后重新运行新安装包再测试。

项目内提供 `installer\ChineseSimplified.isl` 作为 Inno Setup 简体中文语言文件。部分 Inno Setup 安装版本不会自带 `compiler:Languages\ChineseSimplified.isl`，因此脚本默认引用项目内语言文件；如果本机已安装官方简体中文语言文件，也可以将脚本中的 `MessagesFile` 改为 `compiler:Languages\ChineseSimplified.isl`。

安装后的程序文件放在安装目录。运行时产生的用户数据默认放在：

```text
%LOCALAPPDATA%\PMSystem\
```

其中包括 `config.json`、`pm_system.db`、`logs`、`videos` 等。SQLite 使用 Python 内置 `sqlite3`，软件首次启动会自动创建数据库文件和必要目录。这样安装到 `C:\Program Files` 时不会因为普通用户无写入权限导致配置、数据库、日志或视频保存失败。

卸载软件只移除安装目录中的程序文件，不会自动删除已录制视频、日志和配置，避免误删证据文件。

建议打包测试流程：

1. 在干净虚拟环境中执行 `pip install -r requirements.txt`。
2. 执行 `python -m compileall main.py app`。
3. 运行 `python main.py`，确认开发环境正常。
4. 运行 `.\build.bat`。
5. 双击 `dist\电商打包发货监控溯源系统\电商打包发货监控溯源系统.exe`，测试摄像头预览、扫码录制、视频保存、SQLite 查询、播放定位、备注、发货/退货筛选和语音提示。
6. 运行 `.\build_installer.bat`，或使用 Inno Setup 手动编译 `installer\PMSystem.iss`。
7. 在干净电脑或干净用户环境安装测试，确认桌面快捷方式、开始菜单快捷方式、图标、启动和卸载正常。
8. 卸载后确认用户数据目录中的视频、`pm_system.db`、`config.json` 和 `logs` 未被删除。

## 使用注意

- 第一版不录声音，只录制摄像头画面。
- 语音提示使用本地系统语音播报，优先使用 `pyttsx3`，并保留 `pywin32` / Windows SAPI / PowerShell 兜底；如果语音不可用，不影响录制功能。
- 如果程序异常退出，可能留下 `.recording.mp4`、`.temp.mp4` 或 `_temp.mp4` 临时文件；下次启动会提示人工检查，不会自动删除。
- 程序不会自动删除正式视频。查询页删除按钮需要人工确认后才会删除物理文件。
- 安装包卸载程序不会自动删除用户数据目录中的视频、日志和配置。
- `pm_system.db` 保存视频索引、备注、发货/退货类型和重复录制序号。如果需要完整备份，请同时备份视频目录、`pm_system.db` 和 `config.json`。
- 当前版本不使用 MySQL、SQL Server、PostgreSQL 或云数据库；不支持面单图片、不支持自动截图、不支持面单识别。
- OpenCV 在少数机器上可能无法使用某些 mp4 编码；程序会优先尝试 `mp4v`，失败时再尝试其它编码。
