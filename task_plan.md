# OpenXR migration

## Goal
Replace OpenVR with an OpenXR input backend while preserving controller mappings, wheel/flightstick behavior and configuration. Verify with hardware-independent tests; explicitly document runtime/hardware limitations.

## Next Step
等待用户授权硬件共存验收：先启动 SteamVR，确认 mapper 为 Background，测试 ETS2 两种启动顺序及游戏聚焦时输入。当前代码已本地提交；不自动推送或启动 VR/游戏。

### Phase 6: 提交当前改动
**Status:** complete
- 验证：`b44f41642` 退出 0，22 项回归、真实绑定/native smoke、pip check、三个 CLI help、compileall、shell 语法和 flake 解析通过；完整暂存 diff 检查通过。
- 提交：当前改动已在 `main` 创建本地提交，Git 核验工作区干净、相对 `origin/main` 领先 1；收尾记录纳入同一提交，未推送。硬件验收未运行。
- 范围：`/home/zhb/gitrep/fnuipad-VR`，`main`，基准 `faf7b2e61be750c59df554cefe18f29fb71ef678`；仅检查、记录验证并提交既有改动，不扩展实现。
- Writer/owner：当前 Steward，Herdr `wG:p1`；同项目无其他运行 Agent。
- Beads：仓库没有 `.beads`，任务 ID/ownership 无法查询或持久化；不初始化、不切换数据库。本阶段为用户明确授权的独立提交操作。
- Plan：项目根 `task_plan.md`、`findings.md`、`progress.md`。
- 完成标准：离线回归、真实绑定 smoke、pip check、三个 CLI help、Python 编译、shell 语法和 diff 检查通过；提交成功且核验 Git 状态。硬件验收不属于此次提交。
- 失败、并发冲突或需扩大修改范围时停止并报告。

### Phase 5: Restore OpenVR background coexistence
**Status:** complete
Background adapter, launchers/consumers, dependencies and documentation restored. Validation b9382454f passed real binding/library imports, pip check, 22 tests and three CLI help paths without runtime initialization. Hardware coexistence acceptance remains pending.

## Previous incident next step
For the Steam crash incident, ask approval for a controlled retest with only Steam game theatre/desktop capture disabled; preserve driver, Proton and mapper settings initially. Migration hardware acceptance remains pending.

### Incident triage: Steam and ETS2 exit at 00:18
**Status:** complete
Kernel and Steam console establish NVIDIA userspace segfault followed by ETS2 fatal disconnected Steam pipe. Report probable capture/VR overlay involvement without claiming a proven root trigger. No restarts/config changes performed.

## Migration acceptance pending
Hardware acceptance remains: select a runtime advertising XR_MND_headless and test controller inputs, tracking, calibration and concurrent-game focus. No hardware compatibility claim from import/unit tests.

### Phase 1: Inspect architecture and runtime requirements
**Status:** complete

### Phase 2: Implement backend and migrate consumers
**Status:** complete

### Phase 3: Tests, dependencies and documentation
**Status:** in_progress

### Phase 4: NixOS dev shell and China-network dependency setup
**Status:** complete

Use Nix for Python, evdev, Tk and the OpenXR loader; configure Tsinghua PyPI for the Python-only binding. Do not modify system Nix settings or uinput permissions.

## Errors Encountered
- 暂存后 `git diff --cached --check` 首次发现原未跟踪 `task_plan.md` 文件末尾多余空行（工作区 diff 不覆盖未跟踪文件）；仅去除该空行后重新检查完整暂存内容。
- 提交检查：`bd --readonly context --json` / `bd --readonly list --json --limit 30` 报告无 `.beads` / 数据库。保留未知任务状态，不初始化或改用全局库；按用户独立提交授权继续 Git 操作。
- Second OpenVR validation b267509e0: pkg_resources fixed; bundled libopenvr_api_64.so failed to load libstdc++.so.6. ldd confirmed this is its only unresolved dependency in host inspection. Added Nix compiler runtime to library path; verified installed binding pose-query signature accepts count fallback. Third validation pending, no live session.
- OpenVR restoration validation b3b792f13: all 22 tests and compile/shell/diff checks passed; real openvr 1.26.701 import failed because pkg_resources is missing. Pin setuptools 80.9.0 (last pre-removal line) in requirements and setup-python, then repeat real-binding validation without runtime initialization.
- Initial source inspection named nonexistent xr/library_loader.py; actual xr/platform/linux.py confirmed unconditional GLX and optional EGL imports. Continued with existing platform source, no retry of nonexistent file.
- Third native-import validation b4edd2b13 failed in xr.platform.linux -> PyOpenGL GLX: AttributeError: 'NoneType' object has no attribute 'glXGetCurrentContext'. NumPy import progressed; binding imports graphics support even for headless usage. Likely missing GLX/libGL dispatch libraries (libglvnd); not yet verified. Stop repeated validation after three failures per planning protocol; propose Nix-managed transitive dependencies and full platform-import inspection before further changes, pending user direction.
- Locked-shell validation b9461fea7 built successfully but NumPy import required libz.so.1 as well. Inspected all installed NumPy shared objects with ldd: missing entries outside shell were libstdc++ and libz only. Added pkgs.zlib; retry uses dependency inspection rather than another blind import workaround.
- Dev-shell validation b9c79461c: Nix dependencies and Tsinghua installation succeeded; importing xr failed because transitive NumPy wheel could not locate libstdc++.so.6. Added the Nix compiler runtime library to LD_LIBRARY_PATH; next validation uses flake.lock without local override.
- Initial optional-file listing exited 1 (no flake/gitignore); local nixpkgs .git-revision is absent, so do not derive a pin from that file.
- Isolated dependency install b09d0c65d timed out after 120s while installing evdev build dependencies; pyopenxr metadata (1.1.5301) fetched, but installation did not complete. Full binding and hardware checks remain blocked.
- Background binding-type download b834b9c8f failed: curl exit 28, 120002ms timeout, 0 bytes received. Prior partial declarations and downloaded function source remain available; full binding compatibility is unverified. No further retry of this download.
- Default Python has no pip; PyPI download timed out (30s). GitHub raw works; binding functions downloaded, typedef download partial after 15s. Wrong upstream root path returned 404; correct path is src/xr.
- Import cleanup exact-text edit missed because an intervening time import differed; read the actual block and applied the corrected edit.
