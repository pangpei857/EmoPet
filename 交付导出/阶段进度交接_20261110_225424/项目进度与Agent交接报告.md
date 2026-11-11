# 多模态学习陪伴助手：阶段进度与 Agent 交接报告

**报告日期：2026年11月10日（Asia/Shanghai）**  
**项目目录：`C:\Users\20519\Desktop\多模态学习交互助手`**  
**用途：阶段成果交付、跨 Agent 接手开发、后续验收。**

## 1. 接手结论与当前任务

项目已完成一个可运行的 Windows 雨衣皮卡丘桌宠与专注计时原型，已有打包程序。用户已接受桌宠当前形态，下一阶段应集中完成“摄像头预览 → 手机/手部/眉部感知 → 时间策略判断 → 桌宠动作和气泡”的视觉闭环。

**用户最新明确要求：声音交互先不做，其他已规划功能可以开始实现，所需依赖可以直接安装。** 当前应继续摄像头基础、手机检测、提醒联动和表情关怀；叹气检测、麦克风采集、语音播报、语音输入均暂缓。

原开发聊天仍在推进视觉功能。本报告为有时间边界的交接记录，开发中代码不能当作已验收成果。接手前先比较实时目录与随包 `snapshot_manifest.json`，确认原开发聊天是否已完成新的工作，避免重复实现或覆盖改动。此包逐文件读取生成，并非原子文件系统快照。

### 1.1 状态总览

| 范围 | 当前状态 | 交付判断 |
| --- | --- | --- |
| 课题计划 | 已有 Markdown 与 Word 计划书 | 研究方向和阶段安排已形成，须服从最新范围调整 |
| 桌宠外观、互动、窗口、托盘 | 已实现，已有历史实机验证；本次回归通过 | 可作为当前稳定基础 |
| 学习任务、专注/休息计时、本地设置 | 已实现，本次回归与冒烟通过 | 可继续复用 |
| 摄像头进程管理、采集和推理 | 已新增代码，模块导入通过 | 开发中，尚未实机验收 |
| 手机/手部/眉部感知 | 已有推理实现和部分模型 | 开发中，手机 ONNX 权重尚缺 |
| 时间累积、冷却、个人眉部基线 | 已有独立策略代码 | 未接入主界面，缺专项自动化测试 |
| 摄像头面板、纠错入口、事件记录 | 快照中已出现独立CameraPanel，尚未接入主界面；有暂停提醒，无完整纠错/事件日志 | 开发中，待集成验收 |
| 声音与 AI 对话 | 未形成产品能力 | 声音暂缓；大模型非当前闭环依赖 |
| 视觉版 Windows 发布包 | 尚未形成 | 现有 exe 为桌宠稳定版 |

## 2. 已完成成果与必须保留的行为

### 2.1 桌宠

- 使用用户提供的雨衣皮卡丘原画，透明悬浮；启动仅显示桌宠，双击或点击状态条打开学习面板。
- 原画文件为 `assets/raincoat-reference.png`。`raincoat.py` 在绘制时遮罩棋盘格和独立枫叶，保留原图质感；原画来源说明见 `assets/visual-source.md`。
- 眼睛向上下左右及窗口外的鼠标平滑跟随，支持拖动与缩放后的坐标变化。
- 头部、肚子、尾巴有不同点击反馈；拖动不触发点击，双击不额外触发延迟单击。
- 支持呼吸、眨眼、耳尾摆动及待机、关心、提醒、鼓励四类表现，动作结束恢复学习或休息状态。
- 左键拖动、边缘吸附、滚轮每次10%缩放，范围70%—160%；支持置顶、锁定位置、隐藏/恢复、找回桌宠。
- 气泡自动折行，最多显示6行，悬停查看全文并暂停自动关闭；气泡高度变化、收起和切换置顶时保持角色脚下锚点。
- 右键、托盘、面板设置共用入口。隐藏后普通被动提醒不能自动唤回，隐藏取消待触发的点击；锁定后仍可互动与缩放。
- 可用屏幕区域变化后修复位置；单击托盘恢复桌宠，双击打开面板。

现有动画主要通过原画分层变换实现，并无完整走路、坐下等序列帧。用户已同意桌宠先保持当前状态，不应将继续重做美术列为当前主线。

### 2.2 任务、计时与存储

- 支持任务名、15/25/45分钟快捷选项、自定义1—120分钟、开始/暂停/继续/结束、5分钟休息、到点提示。
- `FocusSession` 使用单调时间截止点；界面短暂卡顿不会按丢失 tick 延长计时，暂停时间不计入。
- 关闭面板继续计时；完成轮数避免重复记账。
- `Store` 用 JSON 保存任务、时长、位置、缩放、锁定、气泡、置顶及当日专注摘要，采用临时文件替换写入。
- 默认数据目录由 Qt `AppLocalDataLocation` 决定，应用组织/名称为 `Momo/MomoStudyPet`；通常在 Windows 本地应用数据目录。日志名 `momo.log`，设置名 `settings.json`。
- 当前不是完整历史会话数据库，不具备自动恢复未完成计时、完整事件日志或实验数据管理能力。

### 2.3 运行与发布

- 普通用户双击根目录 `启动桌宠.cmd`；它优先运行 `dist/Momo/Momo.exe`，仅在没有 exe 时回退到源码 Python。
- 本次核对的 exe 修改时间为2026-11-10 16:12:59，早于22时后的视觉开发，不能据此认为视觉功能已发布。
- 分发 exe 时必须带整个 `dist/Momo` 文件夹及许可文件，不能只复制 exe。
- `.artifacts/previous-release-*` 中有历史发布备份，`.artifacts/release-candidate` 有候选产物；它们均不等于当前源码。

## 3. 开发中视觉模块：现状、接口及限制

### 3.1 文件与调用关系

```text
main.py → Companion(ui.py) → PetWindow / FocusPanel / FocusSession / Store

下一阶段待接通：
摄像头面板 → VisionController(camera.py)
                 └─ spawn 子进程 capture_loop(vision_worker.py)
                       └─ VisionEngine(vision.py)
                            ├─ ONNX 手机检测
                            ├─ MediaPipe Face Landmarker
                            └─ MediaPipe Hand Landmarker
                 └─ frame_ready → Observation
                       → ReminderPolicy(perception.py)
                       → Companion.feedback(text, mood)
```

| 文件 | 已有职责 | 接手关注点 |
| --- | --- | --- |
| `study_pet/perception.py` | 纯数据 `Box`、`Observation`、`VisionSettings`、`FeedbackEvent`；时间证据、提醒策略、眉部校准 | 可独立测试，不依赖摄像头或 Qt |
| `study_pet/vision.py` | 预处理/NMS、YOLOv8n COCO手机类别67、Face/Hand Landmarker、结构化观测 | 手机模型缺失时初始化失败；尚无真实识别精度结果 |
| `study_pet/vision_worker.py` | 设备枚举；摄像头或本地视频；640×480采集请求；约8Hz分析目标；释放设备 | 实际帧率取决于 CPU；有界队列优先新帧，未实测吞吐 |
| `study_pet/camera_ui.py` | 新增CameraPanel/PreviewCanvas，设备、镜像预览、设置、3秒校准、暂停10分钟、本地视频测试 | 已有策略与控制器接线，但尚未由Companion创建/接入，未验收 |
| `study_pet/camera.py` | `VisionController`，spawn子进程、有界队列、状态/设备/帧信号、超时和关闭 | 需接入 UI，覆盖启动/关闭/切设备/退出生命周期 |
| `tools/prepare_vision_models.py` | 下载脸/手模型，独立环境导出手机ONNX，生成哈希清单 | `--export-phone` 才导出手机权重；下载成功不等于推理通过 |

`VisionController` 提供 `state_changed(str,str)`、`devices_changed(object)`、`frame_ready(object)`，以及 `refresh_devices()`、`start(source, backend)`、`stop()`、`shutdown()`。帧消息包含 RGB字节、尺寸和 `Observation`。当前进程设计已采用隔离推理，接手应优先完善现有结构。

`Observation` 当前包含单调时间、手机框、手部点、脸框、眉部分数、向下看分数及推理耗时。框和手部点为归一化坐标，预览绘制时要按图像实际显示区域换算，避免缩放/留白造成错框。

### 3.2 当前策略的确切行为

- 默认仅专注期间允许策略触发，并要求恰有一张脸。手机与某只手至少3个关键点靠近才累积“手机在手边”线索；单独出现手机不触发。
- 默认手机线索累积12秒、眉部线索5秒、全局冷却120秒，基础眉部阈值0.45。设置反序列化对数值范围作限制。
- 眉部阈值取基础阈值与“个人基线+0.18”的较大值，最高0.95；校准代码在单人脸连续至少3秒、至少8样本时取中位数。
- 阴性间隔超过1秒清空相应证据；时间倒退或帧间隔超过2秒清空证据。隐藏、稍后提醒、非专注状态会抑制提醒并重置证据。
- 手机事件动作是 `remind`，眉部事件动作是 `care`；当前同次判断手机优先于眉部。

这些是**代码里的初始启发式参数**，不是识别性能承诺，也未按用户数据校准。原计划书中的时间窗口、20—30秒校准、头部姿态辅助及反馈优先级，与当前简化实现有差异，后续须明确采用哪一版并更新文档。

重要缺口：`eyes_down` 已计算但未参与策略，且不能当作头部姿态估计；没有完整低光/遮挡质量门控；新CameraPanel已有“暂停提醒10分钟”、设置和校准入口，并将context回调和反馈作为接入点，但没有“我在查资料/识别错了”的明确纠错入口；尚未与主应用计时、隐藏状态和关机流程接通；无本模块专项测试。现有 `ReminderPolicy` 的 `focus_active` 应严格传入“RUNNING 且 kind 为 focus”，不能把休息或暂停误当专注。

### 3.3 模型和环境

本次查阅的 `assets/models` 有 `face_landmarker.task`、`hand_landmarker.task` 及 `manifest.json`，**缺 `phone_yolov8n.onnx`**。`VisionEngine` 当前要求三个模型齐全才能启动，因此缺权重时摄像头识别闭环尚不能运行。以随包哈希清单为导出文件的最终依据。

实际项目环境为 Python 3.12.14。本次观测的核心版本：PySide6 Essentials 6.12.0、PyInstaller 6.22.3、OpenCV contrib 5.0.0.93、MediaPipe 1.2.2、ONNX Runtime 1.31.1、NumPy 2.5.4、cv2_enumerate_cameras 1.4.0。全部包的观测版本见 `environment_observed.json`，这是已安装环境记录，并非重新安装验证过的锁文件。

根目录 `requirements.txt` 当前只声明 PySide6-Essentials；`requirements-dev.txt` 另加 PyInstaller。**照现有 requirements 新建环境尚不足以复现视觉开发。** 另有 `.artifacts/model-export-venv` 用于模型导出，它没有随交接包复制；接手需核对该环境的导出依赖和导出结果，不要将全部训练工具链混入最终应用。

## 4. 本次验证结果与证据等级

| 检查 | 本次结果 | 能证明什么 |
| --- | --- | --- |
| `unittest discover -s tests -v` | 27项全部通过，约6.9秒 | 6项计时、3项视线、18项桌宠UI测试通过 |
| `main.py --smoke-test` | 退出码0，输出PASS | 开始、暂停、继续、面板恢复、完成、避免重复记账、休息、重启流程通过 |
| 视觉依赖与模块导入 | cv2/NumPy/MediaPipe/ONNX Runtime、VisionController/VisionEngine导入通过 | 包和模块可加载，不等于模型已初始化或摄像头可用 |
| 摄像头实机/手机检测精度 | 本次未做 | 不可声称已验收或给出准确率 |
| 视觉版 exe | 本次未重建 | 不可声称新功能已进入运行版 |

本次 UI 与冒烟检查使用 `QT_QPA_PLATFORM=offscreen`，未操作用户正在运行的桌宠，未开启摄像头。冒烟测试自带临时用户目录，不改用户日常学习记录。随包 `本次源码冒烟预览.png` 为真实控件合成预览，不是视觉识别截图。

历史开发聊天曾报告桌宠打包验证通过，并实测摸头、拖动、位置锁定和滚轮缩放；该结论属于历史记录，区别于本次重新执行的离屏回归。

## 5. 下一位 Agent 的执行任务与验收标准

按以下依赖顺序推进；每步完成后更新状态，避免只写功能而不形成可运行闭环。

### P0：先确认正在进行的改动并补齐运行基础

1. 核对实时文件、原开发聊天状态与此快照；如已有更新先接续成果。当前目录没有 Git 仓库，不能依赖提交号恢复状态，修改前保留副本。
2. 完成或核实手机ONNX导出，检查实际输入输出形状、COCO类别映射和模型哈希。原计划推荐YOLO11n，当前实现选择YOLOv8n导出ONNX，文档应以最终实测版本为准。
3. 补充视觉运行依赖清单，区分应用运行与模型导出环境。用新环境验证依赖能安装、三模型能初始化、能处理一帧并正确释放。

验收：模型齐全并有来源/哈希；模型单帧推理通过；缺模型、缺依赖能给明确错误且桌宠仍可使用。

### P1：交付可用摄像头面板

1. 优先接入现有 `camera_ui.py` 的 `CameraPanel`，不要重做面板。在学习面板增加入口，默认关闭，用户手动开启；核实已有设备选择、刷新、启动、停止、失败重试和状态显示。
2. 复用 `VisionController`，显示预览、手机框、手部与眉部线索、单人/无人/多人状态，明确区分“检测到手机”和“手机靠近手”。
3. 定义面板关闭时的感知行为并明确展示；关闭采集或退出应用必须释放摄像头和子进程。摄像头断开、被占用、权限拒绝、切换设备都能恢复或降级。
4. 默认本机处理，不保存原始视频、不上传；保留桌宠拖动、点击和计时流畅性。

验收：真实摄像头至少完成一次“开启→预览→关闭→再次开启”；关闭后其他应用能获取设备；无设备时计时/桌宠不崩溃；退出无遗留进程。记录本机推理耗时和显示帧率，不能用目标频率当实测结果。

### P2：接通提醒与个性化关怀

1. 完成CameraPanel已有策略接线与Companion的衔接：通过context回调传入专注状态和桌宠显隐，连接 `feedback_requested` 到 `Companion.feedback(event.text, event.mood)`，保持采集帧单调时间。
2. 复用CameraPanel已有提醒开关、阈值/持续时间/冷却设置及个人眉部校准，连接 `settings_changed` 持久化到 `Store`，启动加载时验证范围。
3. 增加“我在查资料”“识别错了”“稍后提醒”等入口；暂停、恢复采集及会话切换时清理过期证据。
4. 增加必要的无媒体事件摘要与可清除入口，记录触发依据、时间和用户纠正，用于后续评估。

验收：合成观测序列证明短时手机、桌面静置手机、非专注、休息、隐藏、无人/多人、冷却期均不误触发；满足持续条件只触发一次；停采/长间隙不继承旧证据；校准和纠错有效。再用真实画面验证端到端动作和气泡。

### P3：回归、打包与交付

1. 运行已有27项回归，补充策略时间边界、坐标换算、队列/进程关闭、模型缺失和推理解析等有意义测试。
2. 更新 `Momo.spec`，纳入视觉模型、MediaPipe/ONNX Runtime及所需动态库；检查 Windows spawn 的 `multiprocessing.freeze_support()` 入口，防止打包后递归启动窗口/进程。
3. 保留现有 ICU DLL 过滤逻辑。历史构建因第三方 ICU 遮蔽系统库曾导致 QtCore 导入失败，不能无依据移除修复。
4. 在候选目录构建，验证打包版打开/关闭摄像头、退出释放资源及中文路径运行，再替换正式目录并保留上一版。
5. 更新 README、依赖、模型清单和本报告状态，写明真实完成范围与剩余问题。

验收：源码版与打包版均完成视觉闭环；普通用户从原启动器打开的是新包；可整体复制运行；测试结果、限制和版本一致。

### 后续研究任务（不阻塞当前视觉交付）

建立带反例的小测试集：看手机、查资料、手机静置、拿笔/计算器、读书低头、皱眉/眯眼、无人/多人、不同光照和遮挡；按人和会话划分开发/测试数据。报告事件精确率/召回率、每小时误提醒数、推理耗时及主观打扰度。先冻结参数再测试。声音路线待用户恢复范围后再启动，不能将纯视觉规则描述为已完成音视频多模态融合研究。

## 6. 接手命令与文件导航

以下以实时项目根目录为工作目录；若使用随包 `source_snapshot`，应先创建自己的 `.venv`。

```powershell
# 源码运行（开发时用它，避免启动器优先打开旧exe）
.\.venv\Scripts\python.exe main.py --profile-dir .artifacts/handoff-qa-profile

# 离屏回归及冒烟验证
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-test --preview-path .artifacts/handoff-preview.png
Remove-Item Env:QT_QPA_PLATFORM

# 模型准备：以下导出命令要求该独立环境已具备导出依赖
.\.artifacts\model-export-venv\Scripts\python.exe tools/prepare_vision_models.py --export-phone

# 正式构建会写入dist；应先保留现有发布版，再按P3要求验证候选包
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

从快照重建桌宠基础环境：`python -m venv .venv`，再运行 `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`。这只覆盖当前声明的桌宠依赖；视觉复现先完成P0依赖整理。

| 优先阅读 | 用途 |
| --- | --- |
| 本报告、`snapshot_manifest.json` | 当前状态、精确文件哈希、任务与验收 |
| `main.py` | 参数、单实例、日志、冒烟、应用入口 |
| `study_pet/ui.py` | 连接新入口、Companion反馈、生命周期 |
| `study_pet/perception.py` | 先补策略专项测试，再联动 |
| `study_pet/camera_ui.py`、`camera.py`、`vision_worker.py`、`vision.py` | 视觉采集到结构化观测 |
| `study_pet/focus.py`、`storage.py` | 任务状态、本地存储 |
| `study_pet/raincoat.py`、`pikachu.py`、`gaze.py` | 稳定的角色绘制与鼠标交互 |
| `tests/` | 已有回归基线 |
| `tools/prepare_vision_models.py`、`Momo.spec`、`build.ps1` | 模型与发布 |
| `课题计划书.md` | 研究目标、评估框架及论文结构；其中声音排期已暂缓 |

`study_pet/art.py` 为较早的猫形象代码，当前主入口采用 `pikachu.py` 和 `raincoat.py`。不要从旧文件或 `.artifacts` 历史草稿继续扩展主线。

## 7. 本交接包的内容与使用方式

- `项目进度与Agent交接报告.md`：可直接阅读或发给下一位 Agent 的主报告。
- `source_snapshot/`：本次导出的源码、测试、配置、README、Markdown计划书、原画与模型资源。
- `snapshot_manifest.json`：快照时间、文件大小和 SHA-256；用来识别后续变更。
- `environment_observed.json`：当前 `.venv` 已安装包版本的观测记录。
- `本次源码冒烟预览.png`：桌宠和学习面板的离屏预览。

未复制 `.venv`、模型导出虚拟环境、`build`、`dist`、历史发布目录、用户本地配置和原始聊天记录。原计划书Word文件仍在项目根目录，本包包含内容来源Markdown。此包用于接手开发，不能作为含视觉功能的可执行发布版；如需分发当前桌宠，另取完整 `dist/Momo` 文件夹。

### 可直接发送给接手 Agent 的任务说明

> 请先阅读本报告和快照清单，并确认实时项目及原开发聊天是否已有更新。沿用现有 Python + PySide6 雨衣皮卡丘桌宠，在不破坏已有27项回归行为的前提下，完成摄像头预览、手机与手部关系检测、眉部关怀及带持续时间/冷却的桌宠提醒。已有 perception/camera_ui/camera/vision_worker/vision 模块处于开发中，优先补齐手机ONNX、依赖、主界面接线与专项测试，不要重新从零搭建。用户已允许安装必要依赖，声音交互暂缓。按报告P0—P3执行，源码与打包版分别验收，最终交付可运行程序、更新后的依赖与说明、测试证据及剩余限制。摄像头默认关闭，本机处理；手机出现与皱眉均只能作为可观察线索，提醒语保持温和。

---
快照生成时间：2026-11-10T22:54:24.904186+08:00
