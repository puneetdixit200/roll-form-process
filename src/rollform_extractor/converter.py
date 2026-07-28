from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile

import ezdxf


ASCII_DXF_INSTRUCTIONS = (
    "No DWG converter found. Export the drawing as AutoCAD 2013 or AutoCAD "
    "2007 ASCII DXF, then run the extractor on that DXF file."
)


class ConversionUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConverterSpec:
    name: str
    executable: Path


@dataclass(frozen=True)
class ConversionResult:
    source_file: Path
    converted_file: Path
    converter: str


def discover_converter() -> ConverterSpec | None:
    for name in ("ODAFileConverter", "ODAFileConverter.exe", "odafileconverter"):
        executable = shutil.which(name)
        if executable:
            return ConverterSpec("oda", Path(executable))
    executable = shutil.which("dwg2dxf")
    if executable:
        return ConverterSpec("libredwg", Path(executable))
    return None


def stage_input(source: Path, destination: Path) -> ConversionResult:
    source = source.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    before = _sha256_file(source)
    try:
        suffix = source.suffix.lower()
        if suffix == ".dxf":
            staged = destination / source.name
            if staged.resolve() == source:
                staged = destination / f"{source.stem}.staged.dxf"
            shutil.copy2(source, staged)
            _validate_dxf(staged)
            return ConversionResult(source, staged, "direct")
        if suffix != ".dwg":
            raise ValueError(f"unsupported CAD file type: {source.suffix}")

        spec = discover_converter()
        if spec is None:
            raise ConversionUnavailableError(ASCII_DXF_INSTRUCTIONS)

        staged = destination / f"{source.stem}.dxf"
        if spec.name == "oda":
            _run_oda(spec.executable, source, staged)
        else:
            _run_libredwg(spec.executable, source, staged)
        _validate_dxf(staged)
        return ConversionResult(source, staged, spec.name)
    finally:
        _assert_unchanged(source, before)


def _run_oda(executable: Path, source: Path, staged: Path) -> None:
    with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as output_dir:
        input_path = Path(input_dir) / source.name
        shutil.copy2(source, input_path)
        failures: list[str] = []
        for version in ("AC1027", "AC1021"):
            command = [
                str(executable),
                input_dir,
                output_dir,
                version,
                "DXF",
                "0",
                "1",
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            candidate = Path(output_dir) / f"{source.stem}.dxf"
            if result.returncode == 0 and candidate.exists():
                shutil.copy2(candidate, staged)
                return
            failures.append((result.stderr or result.stdout or "conversion failed").strip())
    raise _conversion_error("; ".join(failures))


def _run_libredwg(executable: Path, source: Path, staged: Path) -> None:
    with tempfile.TemporaryDirectory() as input_dir:
        input_path = Path(input_dir) / source.name
        shutil.copy2(source, input_path)
        result = subprocess.run(
            [str(executable), "-o", str(staged), str(input_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0 or not staged.exists():
        raise _conversion_error(result.stderr or result.stdout)


def _conversion_error(detail: str = "") -> ConversionUnavailableError:
    detail = detail.strip()
    message = ASCII_DXF_INSTRUCTIONS
    if detail:
        message = f"{message} Converter detail: {detail}"
    return ConversionUnavailableError(message)


def _validate_dxf(path: Path) -> None:
    try:
        ezdxf.readfile(path)
    except Exception as exc:
        raise ValueError(f"not a valid DXF: {path}") from exc


def _assert_unchanged(source: Path, before: str) -> None:
    if _sha256_file(source) != before:
        raise RuntimeError(f"source file was modified: {source}")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
