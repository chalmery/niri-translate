import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from niri_translate.hardware import parse_devices, probe_devices
from niri_translate import storage


class DeviceTests(unittest.TestCase):
    def test_only_real_supported_devices_sorted_by_free_memory(self):
        listing = '''Available devices:
  Vulkan0: AMD Radeon RX 9070 GRE (RADV GFX1201) (12288 MiB, 10000 MiB free)
  Vulkan1: llvmpipe (LLVM 22, 256 bits) (32000 MiB, 30000 MiB free)
  CUDA0: NVIDIA GPU (8000 MiB, 6000 MiB free)
  CPU: Intel CPU (32000 MiB, 31000 MiB free)
  noise without a device
'''
        devices = parse_devices(listing)
        self.assertEqual([d['id'] for d in devices], ['Vulkan0', 'CUDA0'])
        self.assertEqual(devices[0]['name'], 'AMD Radeon RX 9070 GRE (RADV GFX1201)')

    def test_missing_runtime_is_cpu_with_explanation(self):
        result = probe_devices('/not/a/runtime')
        self.assertEqual(result['devices'], [])
        self.assertIn('CPU', result['detail'])


class InventoryTests(unittest.TestCase):
    def test_missing_partial_present_invalid_and_external_paths(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage, 'DATA', Path(tmp)):
            model = storage.MODELS[0]
            path = storage.model_path(model)
            path.parent.mkdir()
            config = {'local_paths': {}}
            self.assertEqual(storage.model_inventory(config)[0]['local_state'], 'missing')
            part = path.with_suffix('.gguf.part')
            part.write_bytes(b'partial')
            info = storage.model_inventory(config)[0]
            self.assertEqual((info['local_state'], info['partial_size']), ('partial', 7))
            path.write_bytes(b'bad')
            self.assertEqual(storage.model_inventory(config)[0]['local_state'], 'invalid')
            external = Path(tmp) / 'external.gguf'
            with external.open('wb') as f: f.truncate(model['size'])
            config['local_paths'][model['id']] = str(external)
            info = storage.model_inventory(config)[0]
            self.assertEqual(info['local_state'], 'present')
            self.assertTrue(info['external'])
            self.assertEqual(info['path'], str(external))
            external.unlink()
            self.assertEqual(storage.model_inventory(config)[0]['local_state'], 'partial')


if __name__ == '__main__': unittest.main()
