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

## Cross-platform artifacts

Windows and macOS binaries should be built on their native platforms.
This repository includes GitHub Actions workflow `.github/workflows/build-desktop.yml`
to build both platforms automatically and upload the resulting artifacts.

## Notes

- Bundled app resources are read-only.
- User-writable cache/config files are stored in the platform app-data directory.
- A local RapidOCR rec-only ONNX model will be bundled when found at:
  `~/.rapidocr_models/ch_PP-OCRv5_rec_mobile.onnx`
