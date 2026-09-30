{
  description = "fnuipad OpenVR Background development environment (Linux)";

  inputs.nixpkgs.url = "https://mirrors.tuna.tsinghua.edu.cn/nix-channels/nixos-unstable/nixexprs.tar.xz";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python312.withPackages (ps: [
            ps.pip ps.evdev ps.tkinter ps.numpy ps.glfw ps.pyopengl
          ]);
          setupPython = pkgs.writeShellApplication {
            name = "setup-python";
            runtimeInputs = [ python ];
            text = ''
              # Rebuild on interpreter/closure changes, preserving the old venv.
              expected='${python}'
              if [ -d .venv ] && { [ ! -f .venv/.nix-python ] || [ "$(< .venv/.nix-python)" != "$expected" ]; }; then
                backup=".venv.backup.$(date +%s).$$"
                mv .venv "$backup"
                echo "Previous environment preserved at $backup"
              fi
              if [ ! -d .venv ]; then
                python -m venv --system-site-packages .venv
                printf '%s\n' "$expected" > .venv/.nix-python
              fi
              .venv/bin/python -m pip install --no-deps --index-url "$PIP_INDEX_URL" 'openvr==1.26.701' 'setuptools==80.9.0'
              echo 'Ready. Activate with: source .venv/bin/activate'
            '';
          };
        in {
          default = pkgs.mkShell {
            packages = [ python pkgs.openxr-loader setupPython ];
            PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple";
            PIP_DISABLE_PIP_VERSION_CHECK = "1";
            # Also cover developers choosing uv rather than the setup helper.
            UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple";
            # xr eagerly imports GLX/EGL even for headless applications.
            # Native Python dependencies are Nix-built, not manylinux wheels.
            # SteamVR also loads libuuid and Vulkan during instance initialization.
            # GPU ICDs remain supplied by the host NixOS graphics configuration.
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
              pkgs.openxr-loader pkgs.libglvnd pkgs.libuuid pkgs.vulkan-loader
              pkgs.stdenv.cc.cc.lib # bundled OpenVR API requires libstdc++.so.6
            ];
            shellHook = ''
              echo 'OpenVR Background dev shell. First use: setup-python'
              echo 'Then: source .venv/bin/activate'
              echo 'Start SteamVR separately; the mapper never acquires a scene.'
            '';
          };
        });
    };
}
