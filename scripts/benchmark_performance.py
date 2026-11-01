"""Offline performance benchmark for catalog and project workloads."""
from __future__ import annotations
import argparse, json, os, platform, shutil, statistics, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from app_forge.catalog.registry import BUILTIN_COMPONENTS, seal_component
from app_forge.services import ForgeServices
from app_forge.settings import ForgeSettings

SEED = BUILTIN_COMPONENTS / "forge.themes" / "1.0.0"

def percentile(values: list[float], fraction: float) -> float:
    if not values or not 0 < fraction <= 1:
        raise ValueError("percentile requires samples and a fraction in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * fraction + 0.999999) - 1)]

def summarize(samples: list[float]) -> dict:
    return {"samples_seconds": samples, "median_seconds": statistics.median(samples),
            "p95_seconds": percentile(samples, .95), "min_seconds": min(samples),
            "max_seconds": max(samples)}

def build_catalog_dataset(root: Path, count: int) -> Path:
    if count < 1: raise ValueError("catalog size must be positive")
    manifest_seed = (SEED / "component.toml").read_text(encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        cid = f"bench.dataset-{i:04d}"
        dest = root / cid / "1.0.0"
        shutil.copytree(SEED, dest)
        manifest = manifest_seed.replace('id = "forge.themes"', f'id = "{cid}"')
        manifest = manifest.replace('name = "Themes (light/dark)"', f'name = "Benchmark Component {i:04d}"')
        manifest = manifest.replace('summary = "Accessible light and dark theme tokens with WCAG contrast validation and a Qt style-sheet generator."',
                                    f'summary = "Synthetic catalog benchmark fixture {i:04d}."')
        (dest / "component.toml").write_text(manifest, encoding="utf-8")
        seal_component(dest)
    return root

def timed(fn, iterations: int) -> list[float]:
    samples=[]
    for _ in range(iterations):
        start=time.perf_counter(); fn(); samples.append(time.perf_counter()-start)
    return samples

def run_benchmarks(workdir: Path, catalog_sizes: list[int], iterations: int) -> dict:
    if iterations < 1: raise ValueError("iterations must be positive")
    workdir.mkdir(parents=True, exist_ok=True)
    catalog=[]
    for size in catalog_sizes:
        root=build_catalog_dataset(workdir/f"catalog-{size}", size)
        svc=ForgeServices(ForgeSettings(home=workdir/f"home-{size}"), builtin_root=None)
        svc.registry._roots=[("benchmark",root)]
        svc.registry.scan(refresh=True)
        scan=timed(lambda: svc.registry.scan(refresh=True),iterations)
        search=timed(lambda: svc.registry.search("benchmark fixture"),iterations)
        catalog.append({"components":size,"scan":summarize(scan),"search":summarize(search)})
    svc=ForgeServices(ForgeSettings(home=workdir/"project-home"))
    out=workdir/"generated-projects"; out.mkdir(exist_ok=True)
    def generate():
        index=len(list(out.iterdir()))
        svc.create_project("cli",{"name":f"Benchmark Project {index:03d}"},out/f"project-{index:03d}")
    projects=timed(generate,iterations)
    return {"schema_version":1,"benchmark":"python-app-forge-performance",
      "recorded_at_utc":datetime.now(timezone.utc).isoformat(),
      "environment":{"platform":platform.platform(),"system":platform.system(),"machine":platform.machine(),
       "processor":platform.processor() or "not reported","python":sys.version,
       "python_version":f"{sys.version_info.major}.{sys.version_info.minor}",
       "python_implementation":platform.python_implementation(),"cpu_count":os.cpu_count(),
       "runner_image":os.getenv("FORGE_RUNNER_IMAGE","unspecified"),
       "runner_image_version":os.getenv("ImageVersion","unknown"),
       "runner_os":os.getenv("RUNNER_OS","unknown"),"runner_arch":os.getenv("RUNNER_ARCH","unknown")},
      "configuration":{"catalog_sizes":catalog_sizes,"iterations":iterations},
      "results":{"catalog":catalog,"project_generation":{"projects_generated":iterations,
       "template":"cli","timing":summarize(projects)}}}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog-sizes",default="25,100,250")
    p.add_argument("--iterations",type=int,default=7)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    try:
        sizes=[int(x.strip()) for x in a.catalog_sizes.split(",") if x.strip()]
        if not sizes or any(x<1 for x in sizes): raise ValueError("catalog sizes must be positive")
        with tempfile.TemporaryDirectory(prefix="forge-benchmark-") as tmp:
            report=run_benchmarks(Path(tmp),sizes,a.iterations)
        rendered=json.dumps(report,indent=2,sort_keys=True)+"\n"
        if a.output:
            a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(rendered,encoding="utf-8")
        print(rendered,end="")
    except (OSError,ValueError,RuntimeError) as exc: p.error(str(exc))
    return 0
if __name__=="__main__": raise SystemExit(main())
