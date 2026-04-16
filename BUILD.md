# Build Desktop App

## Local build

Use the current platform to build its own desktop package:

```bash
python -m pip install --upgrade pip
pip install -r requirements-build.txt
pyinstaller --clean --noconfirm tft_assistant.spec
```

Outputs:

- macOS: `dist/TFT Assistant.app`
- Windows: `dist/TFT Assistant/`

Windows builds embed a UAC manifest that requests administrator permission
when `TFT Assistant.exe` is launched.

## Cross-platform artifacts

Windows and macOS binaries should be built on their native platforms.
This repository includes GitHub Actions workflow `.github/workflows/build-desktop.yml`
to build both platforms automatically and upload the resulting artifacts.

## Notes

- Bundled app resources are read-only.
- User-writable cache/config files are stored in the platform app-data directory.
- On Windows, users will still see the normal UAC confirmation prompt; this
  setting only makes elevation the default launch behavior.
- A local RapidOCR rec-only ONNX model will be bundled when found at:
  `~/.rapidocr_models/ch_PP-OCRv4_rec_mobile.onnx`
