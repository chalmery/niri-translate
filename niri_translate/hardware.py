"""Query the installed runtime, not merely the presence of a graphics card."""
import re
import subprocess


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        match = re.fullmatch(r'\s*(\w+): (.+) \((\d+) MiB, (\d+) MiB free\)\s*', line)
        if not match or not match[1].startswith(('Vulkan', 'CUDA', 'ROCm', 'HIP', 'SYCL')):
            continue
        if any(name in match[2].lower() for name in ('llvmpipe', 'lavapipe', 'software')):
            continue
        devices.append(dict(id=match[1], name=match[2], memory_mib=int(match[3]), free_mib=int(match[4])))
    return sorted(devices, key=lambda d: d['free_mib'], reverse=True)


def probe_devices(binary):
    try:
        result = subprocess.run([str(binary), '--list-devices'], capture_output=True, text=True, timeout=20)
        if result.returncode:
            return dict(devices=[], detail='GPU 检测失败，将使用 CPU；请检查显卡驱动和运行时。')
        devices = parse_devices(result.stdout)
        return dict(devices=devices, detail=('已检测到可用于推理的 GPU' if devices else
                    '当前运行时没有可用 GPU；使用 CPU。若电脑有显卡，请安装 Vulkan 驱动并重新构建运行时。'))
    except (OSError, subprocess.TimeoutExpired):
        return dict(devices=[], detail='运行时不存在或检测超时；使用 CPU。请检查运行时安装。')
