# CausalAgent Windows 客户端

文档职责：说明 CausalAgent Windows WebView2 桌面壳的依赖、配置、开发、打包边界和验收入口。

适用范围：只适用于 `windows-client/` 下的桌面入口；Flask、MySQL、Agent worker、模型、SSE 和文件 API 仍由服务器提供。

## MVP 边界

桌面客户端不是后端的离线打包版，也不是第二套前端。它只创建一个 Windows WebView2 窗口，加载与浏览器相同的 CausalAgent 页面，并继续使用同源 Cookie Session、现有 Flask API、SSE 和文件功能。

MVP 不包含托盘、自动更新、通知、全局快捷键、Token 鉴权、桌面专用 API 或 JavaScript 到本地 Python 的通用调用桥。`create_window` 不传入 `js_api`；网页不能调用桌面 Python 接口。

## 依赖安装

桌面依赖单独维护，不进入后端 Docker 镜像：

```powershell
python -m venv .venv-desktop
.\.venv-desktop\Scripts\python.exe -m pip install -r .\windows-client\requirements-desktop.txt
```

当前验证基线是 CPython 3.12、`pywebview==5.4` 和 Windows Microsoft Edge WebView2 Runtime。依赖文件显式列出 `bottle`、`proxy_tools`、`pythonnet` 及其运行时依赖，避免只安装到 pywebview 而漏掉 Bottle。

如果要运行桌面逻辑测试，再安装只用于测试的扩展依赖；它不会成为 EXE 的运行时入口依赖：

```powershell
.\.venv-desktop\Scripts\python.exe -m pip install -r .\windows-client\requirements-desktop-test.txt
```

检查环境：

```powershell
.\.venv-desktop\Scripts\python.exe .\Run_causal.py --check-environment
```

如果当前目录已经是 `windows-client/`，也可以执行：

```powershell
..\.venv-desktop\Scripts\python.exe -m causalagent_desktop --check-environment
```

检查命令会报告 Python 版本、Windows 平台、pywebview 完整导入、固定版本和 WebView2 Runtime。失败时只显示可操作的中文提示，不显示 Python traceback、Cookie、Token、查询正文或完整异常。

## 启动配置

兼容入口仍然是：

```powershell
.\.venv-desktop\Scripts\python.exe .\Run_causal.py
```

如果当前目录已经是 windows-client/，也可以直接调用模块：

```powershell
..\.venv-desktop\Scripts\python.exe -m causalagent_desktop
```

URL 优先级为：命令行 `--url`，然后是 `CAUSALAGENT_DESKTOP_URL`，最后是模式默认值。

开发模式默认加载 `http://127.0.0.1:5001/`，并允许 `http://localhost:5001/`；为运行隔离 stub，也允许显式配置的本地回环端口。开发模式可使用 `--debug` 或 `CAUSALAGENT_DESKTOP_DEBUG=true`。

Release 模式必须使用预先配置的 HTTPS origin：

```powershell
$env:CAUSALAGENT_DESKTOP_MODE = "release"
$env:CAUSALAGENT_DESKTOP_RELEASE_ORIGIN = "https://causalagent.example.com"
$env:CAUSALAGENT_DESKTOP_URL = "https://causalagent.example.com/"
.\.venv-desktop\Scripts\python.exe .\Run_causal.py
```

Release 模式强制关闭 debug、开发者工具和开发地址；正式安装包应在构建/安装阶段写入正式的 `CAUSALAGENT_DESKTOP_RELEASE_ORIGIN` 与 `CAUSALAGENT_DESKTOP_URL`，不应依赖本地默认值。

WebView2 数据目录固定为 `%LOCALAPPDATA%\CausalAgent\WebView`，并以 `private_mode=False` 启动，让服务器 Session Cookie 和 localStorage 能按服务器策略跨客户端重启保存。可通过 `CAUSALAGENT_DESKTOP_ICON` 指定 `.ico` 应用图标路径；PyInstaller 发行物还应在构建命令中使用相同的 `.ico` 作为 EXE 图标。

## 导航与错误处理

桌面壳使用原生 Edge WebView2 导航事件执行策略：

- 配置 origin 内的页面留在客户端，包含普通路径、查询和片段。
- 外部 `https` 导航取消 WebView 导航并交给系统浏览器。
- `file://`、`javascript:`、未知协议、外部 HTTP 和非白名单 HTTPS 导航全部取消。
- 新窗口请求同样经过该策略；普通站内 `target="_blank"` 会在当前客户端窗口加载，错误页的“在浏览器中打开”才交给系统浏览器。
- 不信任网页传入的 URL，不打印导航 URL、Cookie、Token 或查询正文。

WebView2 Runtime 缺失或初始化失败时显示中文提示。服务器无法访问时，客户端页面显示当前访问 origin、重新加载和在浏览器中打开三个操作；不会把内部异常展示给用户，也不会无限保持无提示的白屏。

## 测试

纯逻辑测试不启动真实窗口：

```powershell
.\.venv-desktop\Scripts\python.exe -m pytest windows-client/tests/test_config.py windows-client/tests/test_navigation_policy.py windows-client/tests/test_runtime.py windows-client/tests/test_launcher.py -q
```

真实 Windows 壳层 smoke 默认跳过，显式开启后会启动隔离的本地 HTTP stub，验证页面加载、Edge Chromium renderer、窗口自动关闭和进程退出：

```powershell
$env:CAUSALAGENT_DESKTOP_RUN_SMOKE = "1"
.\.venv-desktop\Scripts\python.exe -m pytest windows-client/tests/test_windows_smoke.py -q
Remove-Item Env:CAUSALAGENT_DESKTOP_RUN_SMOKE
```

如果运行环境没有可用的桌面会话、WebView2 Runtime 或固定桌面依赖，smoke 不应被伪装成通过；应保留失败原因并在验收报告中区分“逻辑测试通过”和“真实 Windows 壳层未执行”。

## 打包边界

第一版只打包桌面壳和其 Python 运行时，不复制 Flask、MySQL、worker、模型、知识库索引或后端 Docker 依赖。发行物必须：

1. 固定正式 HTTPS origin，并使运行时白名单只包含该 origin。
2. 强制 `edgechromium`，目标机预先安装 WebView2 Runtime。
3. 关闭 debug 和开发者工具。
4. 保留 `%LOCALAPPDATA%\CausalAgent\WebView` 的用户数据目录策略。
5. 服务器前端更新后直接重新加载即可看到新页面，不因页面更新重新打包桌面壳。

在 Windows 环境中构建 onedir 或 onefile 包：

```powershell
powershell -ExecutionPolicy Bypass -File .\windows-client\build.ps1 `
  -ReleaseOrigin "https://causalagent.example.com" `
  -PackageMode onedir `
  -IconPath "C:\path\to\CausalAgent.ico"
```

构建脚本会把公开的 HTTPS origin 嵌入包内；冻结后的 EXE 默认强制 release，即使运行环境没有配置变量也不会回退到 `127.0.0.1`。`-IconPath` 是可选的 `.ico`，但正式发布应提供并在 EXE 和窗口配置中使用正式图标。构建输出属于本地产物，不提交 `build/`、`dist/` 或生成的 `.spec`。
