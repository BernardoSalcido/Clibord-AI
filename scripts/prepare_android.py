"""Download a portable Android build toolchain from official distributors.

Everything stays under .tools. No PATH, registry, or global SDK is modified.
"""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
TOOLS.mkdir(exist_ok=True)


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ClipboardAI-build/0.1"}), timeout=90) as response:
        return response.read()


def download(url, name, digest, algorithm="sha256"):
    path = TOOLS / name
    if not path.exists():
        print(f"Descargando {name}...", flush=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(path)
    actual = hashlib.new(algorithm, path.read_bytes()).hexdigest()
    if actual.lower() != digest.strip().lower():
        raise RuntimeError(f"Checksum incorrecto: {path.name}")
    return path


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Ruta insegura en archivo descargado")
        bundle.extractall(destination)


def main():
    java_dirs = list(TOOLS.glob("jdk-*/bin/java.exe"))
    if not java_dirs:
        assets = json.loads(fetch("https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse"))
        package = assets[0]["binary"]["package"]
        unpack(download(package["link"], package["name"], package["checksum"]), TOOLS)
    version = "8.11.1"
    if not (TOOLS / f"gradle-{version}/bin/gradle.bat").exists():
        url = f"https://services.gradle.org/distributions/gradle-{version}-bin.zip"
        checksum = fetch(url + ".sha256").decode()
        unpack(download(url, f"gradle-{version}-bin.zip", checksum), TOOLS)
    repository = ET.fromstring(fetch("https://dl.google.com/android/repository/repository2-1.xml"))
    sdk = TOOLS / "android-sdk"
    for package_id, relative in [("platforms;android-35-ext15", "platforms/android-35-ext15"),
                                  ("build-tools;35.0.0", "build-tools/35.0.0"),
                                  ("platform-tools", "platform-tools")]:
        destination = sdk / relative
        if (destination / "source.properties").exists():
            continue
        package = next(p for p in repository.findall("remotePackage") if p.attrib["path"] == package_id)
        archives = package.find("archives").findall("archive")
        archive = next(a for a in archives if a.findtext("host-os") in (None, "windows"))
        complete = archive.find("complete")
        checksum = complete.find("checksum")
        url = complete.findtext("url")
        zipped = download("https://dl.google.com/android/repository/" + url, url,
                          checksum.text, checksum.attrib.get("type", "sha1"))
        staging = TOOLS / (package_id.replace(";", "-") + "-unpacked")
        unpack(zipped, staging)
        children = list(staging.iterdir())
        source = children[0] if len(children) == 1 and children[0].is_dir() else staging
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise RuntimeError(f"Destino parcial existente: {destination}. Revisar antes de repetir.")
        shutil.move(str(source), str(destination))
    java = list(TOOLS.glob("jdk-*/bin/java.exe"))[0].parent.parent
    config = {"java": str(java), "sdk": str(sdk), "gradle": str(TOOLS / f"gradle-{version}/bin/gradle.bat")}
    (TOOLS / "android-env.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("Entorno listo en .tools/android-env.json", flush=True)


if __name__ == "__main__":
    main()
