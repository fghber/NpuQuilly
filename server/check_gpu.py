"""Verify OpenVINO sees Xe3 GPU + NPU. Run: python check_gpu.py"""
def main():
    try:
        import openvino as ov
    except ImportError:
        print("openvino not installed. Run: pip install -r requirements.txt")
        return 1
    core = ov.Core()
    devices = core.available_devices
    print(f"Available OpenVINO devices: {devices}")
    for d in devices:
        try:
            name = core.get_property(d, "FULL_DEVICE_NAME")
            print(f"  {d}: {name}")
        except Exception as e:
            print(f"  {d}: (name query failed: {e})")
    if not any(d.split('.')[0] == "GPU" for d in devices):
        print("GPU not visible. Check the Intel Graphics driver; CPU mode is available.")
    if not any(d.split('.')[0] == "NPU" for d in devices):
        print("NPU not visible. Check the Intel AI Boost driver.")
        print("GPU-only mode still works for NpuQuilly.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
