# NpuQuilly

NpuQuilly is a Windows tray app for proofreading, rewriting, and summarizing
selected text. It uses OpenVINO to run a downloaded model on a compatible Intel
GPU or NPU, or on the CPU.

## Start on Windows

1. Install 64-bit Python 3.12 with the Windows Python launcher. [Python downloads](https://www.python.org/downloads/windows/)
2. Open PowerShell in the project folder and run the one-time setup.

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Setup-NpuQuilly.ps1 -Model grammar-fast
   ```

   Setup creates a virtual environment, installs dependencies, prints the
   available OpenVINO devices, and downloads the default model. The download
   requires an Internet connection and several gigabytes of disk space. Run setup
   without `-Model` to install or repair dependencies only.

3. Double-click **run.cmd**. If OpenVINO reports no GPU, select **CPU** in the
   tray app's **Settings**.

Select text in an editor and use a shortcut.

| Shortcut | Action |
| --- | --- |
| Ctrl+Shift+G | Proofread |
| Ctrl+Shift+R | Rewrite |
| Win+Shift+Q | Choose an action, including Summarize or Custom |
| Ctrl+Shift+Space | Repeat the last action |
| Esc | Dismiss the dialog |

The preview opens by default. **Accept (paste)** replaces the original selection
after the app verifies the source window and selected text. **Copy** gives you
the result for manual use. Use the tray menu for Settings, Pause, or Quit. Quit
stops the app-owned backend and releases its model memory.

## Models

| Alias | Device | Source |
| --- | --- | --- |
| `grammar-fast` | GPU or CPU | `OpenVINO/Phi-4-mini-instruct-int4-ov` |
| `grammar-battery` | NPU | `Fede2782/Phi-4-mini-instruct-int4-cw-ov` |
| `rewrite-alt` | GPU or CPU | `Aditya02/Qwen3-4B-Instruct-2507-ov-int4` |

In **Settings > Device**, choose a device and click **Download model weights**.
For GPU and CPU, the button uses the model alias on the **API** tab. For NPU,
it downloads `grammar-battery`. Keep Settings open until the download finishes,
then click **OK** to apply your settings. Downloads are resumable and stored
under `server/models/`.

You can also fetch weights from PowerShell.

```powershell
$python = '.\NpuQuilly\.venv\Scripts\python.exe'
& $python .\server\download_model.py --alias grammar-battery
& $python .\server\download_model.py --alias rewrite-alt
```

NPU mode selects `grammar-battery` for all actions and allows up to 1,024 input
tokens including instructions. GPU and CPU use the selected model. The first
request on each device can take several minutes while OpenVINO compiles the model.
Dependencies and model weights are retrieved separately under their upstream
licenses.

## Privacy and troubleshooting

- The default backend listens on `127.0.0.1:8000`. With a downloaded model and
  the default settings, inference can run offline. Keep this unauthenticated
  endpoint on loopback.
- If you configure a different API endpoint, selected text and instructions are
  sent to that endpoint. The app can also reuse an independently started
  service at the default address.
- The app uses the Windows clipboard for capture and paste. Clipboard history
  and sync can retain those entries if enabled. The app also registers global
  hotkeys while running.
- Settings and windowless diagnostics are stored under `%APPDATA%\NpuQuilly`.
  New API keys are encrypted with Windows DPAPI. Review diagnostics before
  sharing them because they may include local paths and system details.
- If startup fails, see `%APPDATA%\NpuQuilly\npuquilly.log` or run
  `powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Start-NpuQuilly.ps1`
  for dependency checks. With the default backend running,
  `http://127.0.0.1:8000/health` lists available devices and loaded models.

## Development

```powershell
$python = '.\NpuQuilly\.venv\Scripts\python.exe'
& $python -m pip install -r requirements-dev.txt
& $python -m pytest -q
& $python .\NpuQuilly\main.py --smoke
& $python .\eval\ab_test.py --dry-run
```

The tests use simulated inference. With the app running and a model downloaded,
use `& $python .\eval\validate.py --device GPU --model grammar-fast` to test
the actual model on the included samples. Evaluation tools write results under
the ignored `eval/reports/` directory. Reports can include the original
passages and model responses.

## License

Copyright 2026 fghber. NpuQuilly is available under the [Apache License, Version 2.0](LICENSE).
