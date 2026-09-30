# Progress

## 用户授权提交代码（2026-09-30）
- 已恢复根 planning 三文件并核对 Git：`main`，基准 `faf7b2e`，10 个已跟踪文件修改及后端、测试、Nix/launcher/planning 新文件；无已暂存改动。
- Herdr 当前项目仅本 Steward `wG:p1` 在执行，没有同项目其他 Agent。仓库无 AGENTS.md、无 `.beads`；Beads 查询失败，未初始化或切换数据库，也不修改任务状态。
- 仅复跑离线验收并提交现有改动；不推送，不自动启动 VR/游戏，不修改产品实现。虚拟环境、字节码和 `.pi/tasks` 按现有 `.gitignore` 排除。
- 本次离线检查 `b44f41642` 退出 0：22 项单元回归全部通过，真实 OpenVR 绑定/原生库 smoke 通过，pip check 无依赖问题，三个入口 `--help`、compileall、shell 语法、flake 解析及 `git diff --check` 均通过。仅有已知 `pkg_resources` 弃用警告；未初始化 VR/uinput。
- 完整暂存 diff 检查发现原未跟踪 `task_plan.md` 末尾多余空行；只修正此格式问题后检查通过。24 个代码、测试、配置、文档和 planning 文件已创建本地提交：`feat: 添加 OpenVR Background 后端和 Nix 启动环境`。提交后核验工作区干净，`main` 相对 `origin/main` 领先 1；本条收尾记录纳入同一提交，不新增第二个提交。
- 未推送，未运行硬件验收，未改变 Beads task 状态。长期知识中 OpenVR Background 共存限制与 setuptools 兼容约束已在 README/现有 planning 留存，缺 Beads 无法补充 memory。
- Next Step：等待用户授权 SteamVR/ETS2 硬件共存验收，不自动启动或更改运行环境。

## First live OpenVR Background attempt
- be88f45af exited 1 at initialization. vrclient_python.txt at 00:42:27 identifies PID 41387 as VRApplication_Background, then IPC connection refused (errno=111), explicitly refusing to auto-start vrserver for a Background application. Process inspection finds no vrserver/compositor. This is a missing running SteamVR prerequisite, not a scene takeover. Start SteamVR before retry; no runtime/game auto-launch performed. Background client identity verified, live input/coexistence still pending.

## OpenVR Background restoration implementation
- FINAL offline validation b9382454f exited 0: OpenVR native dependency resolution and real binding/structure smoke passed, pip check clean, all 22 regression tests passed, all three CLI help paths passed. No SteamVR session or uinput device initialized. pkg_resources deprecation warning remains nonfatal with setuptools pinned. Live Background classification, launch-order coexistence and foreground-game input remain unverified.
- Second validation b267509e0 passed package setup but OpenVR native load lacked libstdc++.so.6. ldd identified the missing library; flake now supplies pkgs.stdenv.cc.cc.lib. Third validation b9382454f running; no runtime initialization.
- First validation b3b792f13 passed 22 tests and compile/shell/diff checks; native binding import blocked by missing pkg_resources. Added setuptools==80.9.0 to setup-python/requirements and documented compatibility constraint. Retry b267509e0 runs real imports, pip check, regressions and CLI help only; no live session.
- Added _openvr.py snapshot adapter using only VRApplication_Background, system pose queries (no compositor), role rediscovery, axis-type detection, quit acknowledgment and shutdown. Switched all three launchers and four consumers to it; preserved mapping/uinput and disabled overlays.
- Pinned openvr 1.26.701 in requirements/setup-python, updated real-binding smoke and README, enabled unbuffered launcher output. Added eight fake-runtime regression tests. Legacy OpenXR code is unselected, retained for prior tests only.
- Validation b3b792f13 running: unit/compile/diff/shell checks, locked Nix setup, real OpenVR imports/structures, pip check and all CLI help. No live VR init or game launch. Existing old process is not automatically replaced by editing files; must stop it before live testing.

## Confirmed SteamVR scene-slot conflict
- vrserver.txt proves both directions: ETS2 launch sends Quit then kills mapper 37864 at 00:24:45; mapper 38886 launch sends Quit to ETS2 38557 at 00:25:41 then kills it at 00:25:46. Active SteamVR promotes headless mapper to OpenXRScene. This explains exit 137 and latest game termination, superseding driver speculation for these incidents. No code/process changes made; report correction and propose background-compatible backend before further launches.

## Steam / ETS2 incident triage (2026-09-26 00:18)
- Correlated kernel journal, Steam console, current process list and ETS2 logs. Steam segfaulted in NVIDIA GL core at 00:18:25; ETS2 process 34541 exited on disconnected Steam IPC at 00:18:28. VR game overlay/capture errors precede the crash. No recent kernel OOM/GPU-reset match in inspected 20-minute window.
- Mapper and SteamVR remain running; no proof mapper caused crash and no proof it is unrelated. Old ETS2 crash report excluded by timestamp. Only planning notes updated; no code, settings or processes changed. Recommend single-variable game theatre/capture-disabled retest with user approval.

## Runtime-loss abort mitigation
- b2c1046f1 passed dependency checks and 13 tests, initialized XR and uinput at 23:56:58, then exited 134 at 23:59:14. SteamVR logs show Steam shutdown at 23:59:07, client server-connection loss at 23:59:09 and native assertion after ignoring quit for 5 seconds. No stack trace proves the blocking call; compositor wait is a candidate, not confirmed root cause of Steam shutdown.
- Removed compositor frame calls from headless polling; use CLOCK_MONOTONIC converted by XR_KHR_convert_timespec_time via explicit proc lookup. This adds a required extension and avoids blocking event polling on xrWaitFrame. 14 regression tests and compile/diff checks pass, including no-frame-wait and exit event tests. Live mitigation not yet verified; do not claim native runtime crashes are fully prevented.

## Connected-headset Vulkan fix
- b57c9f821 reached SteamVR with headset connected but xrCreateInstance failed. Correlated PID 23235 with xrclient_python.txt: failed to find vulkan library; failed to initialize graphics requirements. Added pkgs.vulkan-loader to flake library path and smoke checks for libvulkan.so and libvulkan.so.1. User authorized continuation; b2c1046f1 runs smoke/regression checks followed by the actual mapper. No SteamVR/game restart requested or performed.

## Live startup diagnosis
- Ran ./start.sh as requested (b92219c5a, exit 1). Loader now reaches xrCreateInstance. Correlated process 21794 with SteamVR client/server logs: VRInitError_Driver_WirelessHmdNotConnected. Runtime refused connection because wireless HMD is disconnected; server and monitor are still running. No XR session/uinput creation reached. Do not patch around or loop retry a hardware precondition; user must connect headset before further live verification.

## SteamVR libuuid fix
- Added pkgs.libuuid to the flake library path and libuuid loading to tests/smoke_nix.py.
- Validation b0f0df623 exited 0: libuuid/loader/GLX/EGL load successfully, real binding smoke checks and 13 regression tests pass. ldd on the active SteamVR vrclient.so reports no missing linked libraries. No XR session started; headless extension/runtime behavior still requires live verification.

## Launcher
- Added executable start.sh for gamepad/wheel/flightstick; enters locked Nix shell, runs setup-python and execs the selected entry point with safely forwarded arguments. README updated.
- bash syntax, launcher help and invalid-mode exit checks passed. End-to-end ./start.sh gamepad --help completed successfully (bdca3fac1, exit 0). This verifies the startup path without hardware, not a live XR session.

## NixOS development environment
- FINAL RESULT: b77e7214a exited 0 using locked nixpkgs. Fresh venv installed only pyopenxr 1.1.5301 from Tsinghua. numpy/glfw/OpenGL/evdev/tkinter origins verified in /nix/store; loader, GLX and EGL loaded successfully. Real binding structure smoke checks passed, pip check reported no broken requirements, all 13 regression tests passed. Old venv preserved at .venv.backup.1790347767.236896. Phase 4 complete; remaining migration acceptance is hardware/runtime testing, not dependency installation.
- User approved revised Nix approach. Flake now supplies numpy/glfw/pyopengl and libglvnd; removed ad-hoc wheel library fixes. setup-python installs only pyopenxr (--no-deps), preserves old/stale venvs and records the Nix Python closure path. README and gitignore updated.
- Added tests/smoke_nix.py to check dependency origins, loader/GLX/EGL loading and actual binding structures. Nix parsing, diff check, shell syntax and 13 unit tests pass. Background b77e7214a validates locked shell, fresh venv, smoke test, pip check and regressions; pending result.
- b4edd2b13 failed in PyOpenGL GLX during xr.platform.linux import: NoneType has no glXGetCurrentContext. NumPy no longer blocks import. Binding eagerly imports graphics support despite headless backend. Three validation failures reached: stop and ask before further retries. Likely next design: Nix-managed NumPy/glfw/PyOpenGL and libglvnd, verify full binding platform imports, then test a fresh venv. Not yet implemented or validated.
- Locked-source shell b9461fea7 built successfully; xr import exposed missing zlib after the C++ runtime fix. ELF dependency inspection found only libstdc++/libz unresolved outside the shell. Added zlib and launched b4edd2b13 for real imports and regression tests; verification pending.
- Validation b9c79461c built the shell and imported Nix evdev/Tk successfully. Tsinghua installed pyopenxr 1.1.5301 plus its NumPy/glfw/PyOpenGL dependencies. xr import then failed on missing libstdc++.so.6; added stdenv.cc.cc.lib to shell LD_LIBRARY_PATH. Retest b9461fea7 uses the actual locked nixpkgs (no override); result pending.
- User clarified mainland-China networking and requested a flake dev shell.
- Added flake.nix: Nix Python 3.12 + evdev + Tk + OpenXR loader; setup-python explicitly installs pinned pyopenxr into .venv via Tsinghua. No automatic pip on shell entry and no system settings changes.
- Added .gitignore for local venv/bytecode/task logs. README includes Nix workflow, loader/runtime distinction and declarative uinput permissions. Legacy setup-script now refuses NixOS and uses Tsinghua elsewhere.
- Nix parse, shell syntax, diff whitespace and 13 regression tests pass. Mirror lock fetch completed successfully (bd6a46536, exit 0); flake.lock records the Tsinghua source URL and NAR hash. Actual dev-shell realization/import test using the local nixpkgs override remains pending; it does not verify the newly locked source.

- Started migration; checked initial diff and established planning files.
- Inspected all consumers and official headless extension semantics. Selected explicit headless-only support (no rendering fallback that would steal foreground focus).
- Added runtime-independent snapshots/quaternion conversion. Migrated named mapping inputs; removed legacy overlay classes from wheel/flightstick and added tracking-loss neutralization and edit-mode discovery.
- Added OpenXR actions/bindings for Vive, Touch, Index, simple and Microsoft motion profiles; shared session lifecycle, pose sampling and haptics. Migrated all entry points and dependency setup. Compile check passes.
- 13 hardware-independent tests pass, including wheel/flightstick lost tracking and calibration. compileall, shell syntax and git diff --check pass. Removed now-unnecessary numpy dependency (wheel unwrap uses standard-library math).
- README documents required headless support, unsupported overlays/system buttons, LOCAL-space calibration and hardware acceptance steps. Full binding declaration download failed (curl exit 28, 120s, zero bytes); no repeat download planned. Isolated dependency installation also timed out after 120s at evdev build dependency installation (pyopenxr 1.1.5301 metadata fetched only). Real binding compatibility remains unverified; no background checks remain running. Phase 3 is blocked pending usable dependencies/runtime.
