"""PyInstaller build: python build.py -> dist/NpuQuilly.exe"""
import PyInstaller.__main__ as pm
from pathlib import Path

root = Path(__file__).resolve().parent

pm.run([str(root / "main.py"), "--name", "NpuQuilly", "--windowed", "--onefile",
        "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
        "--specpath", str(root),
        "--add-data", f"{root / 'resources' / 'default_prompts.json'};resources"])
print("Built dist/NpuQuilly.exe")
