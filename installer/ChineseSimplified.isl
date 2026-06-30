; Simplified Chinese messages for the installer.
; This local file is used because some Inno Setup installations do not ship
; compiler:Languages\ChineseSimplified.isl by default.

[LangOptions]
LanguageName=简体中文
LanguageID=$0804
LanguageCodePage=936
DialogFontName=Microsoft YaHei UI
DialogFontSize=9
WelcomeFontName=Microsoft YaHei UI
WelcomeFontSize=12
TitleFontName=Microsoft YaHei UI
TitleFontSize=29
CopyrightFontName=Microsoft YaHei UI
CopyrightFontSize=8

[Messages]
SetupAppTitle=安装程序
SetupWindowTitle=安装 - %1
UninstallAppTitle=卸载程序
UninstallAppFullTitle=卸载 %1

InformationTitle=信息
ConfirmTitle=确认
ErrorTitle=错误

ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全部是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全部否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonWizardBrowse=浏览(&R)...
ButtonNewFolder=新建文件夹(&M)

SelectDirDesc=请选择 [name] 的安装位置
SelectDirLabel3=安装程序会将 [name] 安装到以下文件夹。
SelectDirBrowseLabel=如需继续，请点击“下一步”。如需选择其他文件夹，请点击“浏览”。
SelectStartMenuFolderDesc=请选择开始菜单文件夹
SelectStartMenuFolderLabel3=安装程序会在以下开始菜单文件夹中创建程序快捷方式。
SelectStartMenuFolderBrowseLabel=如需继续，请点击“下一步”。如需选择其他文件夹，请点击“浏览”。
SelectTasksDesc=请选择要执行的附加任务
SelectTasksLabel2=请选择安装 [name] 时需要执行的附加任务，然后点击“下一步”。
ReadyLabel1=安装程序已准备好开始在您的电脑上安装 [name]。
ReadyLabel2a=点击“安装”继续安装；如需查看或修改设置，请点击“上一步”。
ReadyLabel2b=点击“安装”继续安装。
ReadyMemoDir=安装位置：
ReadyMemoGroup=开始菜单文件夹：
ReadyMemoTasks=附加任务：
ReadyMemoType=安装类型：
ReadyMemoComponents=已选择组件：
ReadyMemoUserInfo=用户信息：
InstallingLabel=请稍候，安装程序正在安装 [name]。
FinishedHeadingLabel=正在完成 [name] 安装向导
FinishedLabelNoIcons=安装程序已在您的电脑上完成 [name] 的安装。
FinishedLabel=安装程序已在您的电脑上完成 [name] 的安装。可以通过已创建的快捷方式启动程序。
FinishedRestartLabel=为了完成 [name] 的安装，安装程序必须重新启动电脑。是否现在重新启动？
FinishedRestartMessage=为了完成 [name] 的安装，安装程序必须重新启动电脑。%n%n是否现在重新启动？
ClickFinish=点击“完成”退出安装程序。

WizardSelectDir=选择安装位置
WizardSelectProgramGroup=选择开始菜单文件夹
WizardSelectTasks=选择附加任务
WizardReady=准备安装
WizardInstalling=正在安装
WizardFinished=安装完成

ExitSetupTitle=退出安装程序
ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会被安装。%n%n您可以稍后再次运行安装程序完成安装。%n%n确定要退出安装程序吗？
AboutSetupMenuItem=关于安装程序(&A)...
AboutSetupTitle=关于安装程序
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=该向导将在您的电脑上安装 [name/ver]。%n%n建议在继续安装前关闭其他应用程序。

BeveledLabel=
NewFolderName=新建文件夹
SelectDirBrowseCaption=选择文件夹
SelectStartMenuFolderBrowseCaption=选择文件夹
SelectDirectoryLabel=请指定下一张磁盘的位置。
NoProgramGroupCheck2=不创建开始菜单文件夹(&D)
DiskSpaceMBLabel=至少需要 [mb] MB 可用磁盘空间。
DiskSpaceGBLabel=至少需要 [gb] GB 可用磁盘空间。
CannotContinue=安装程序无法继续。请点击“取消”退出。

ErrorOpeningFile=打开文件时出错：%n%1%n%n请点击“重试”重新尝试，或点击“取消”停止安装。
ErrorFunctionFailed=调用函数 %1 失败；错误代码 %2。
ErrorFunctionFailedWithMessage=调用函数 %1 失败；错误代码 %2。%n%3
ErrorExecutingProgram=无法执行文件：%n%1
SetupAborted=安装未完成。%n%n请修正问题后重新运行安装程序。
SetupLdrStartupMessage=即将安装 %1。是否继续？

UninstallStatusLabel=请稍候，正在从您的电脑中卸载 %1。
UninstalledAll=%1 已成功从您的电脑中卸载。
ConfirmUninstall=确定要完全移除 %1 及其所有组件吗？
UninstallOnlyOnWin64=此安装只能在 64 位 Windows 上卸载。
OnlyAdminCanUninstall=只有具有管理员权限的用户才能卸载此程序。

StatusExtractFiles=正在解压文件...
StatusCreateDirs=正在创建目录...
StatusCreateIcons=正在创建快捷方式...
StatusCreateIniEntries=正在创建 INI 项...
StatusCreateRegistryEntries=正在创建注册表项...
StatusRegisterFiles=正在注册文件...
StatusSavingUninstall=正在保存卸载信息...
StatusRunProgram=正在完成安装...
StatusRollback=正在回滚更改...
RunEntryExec=运行 %1
RunEntryShellExec=查看 %1
