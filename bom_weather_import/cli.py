"""CLI orchestration and diagnostics. Exit codes: usage 2, input 3, calibration 4, output 5."""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sys

from . import __version__
from .bom import BomDatasetReader, PRODUCTS
from .calibration import calibrate
from .data import CalibrationError, InputError, JoinedWeatherDataset, VARIABLES
from .output import ImportReportWriter, JsonWeatherModelWriter, WeatherModelBuilder


def iso_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parser():
    p = argparse.ArgumentParser(prog="bom-weather-import", description="Calibrate BOM dataset directories into a CorrelatedMonthlyWeather JSON definition.")
    for arg in ("solar", "tmax", "tmin"):
        p.add_argument("--" + arg, required=True, type=Path, metavar="DIRECTORY")
    for arg in ("start-date", "end-date"):
        p.add_argument("--" + arg, required=True, type=iso_date)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--model-name", default="BOMWeatherModel")
    p.add_argument("--location-name")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--include-timestamp", action="store_true", help="Include current UTC generation time (otherwise JSON is byte reproducible)")
    p.add_argument("--version", action="version", version=__version__)
    return p


def warn(message):
    print("WARNING: " + message, file=sys.stderr)


def run(options):
    if options.start_date > options.end_date:
        raise InputError("Training start must be on or before end")
    if not options.model_name.strip():
        raise InputError("Model name must not be blank")
    reader = BomDatasetReader()
    directories = dict(zip(VARIABLES, (options.solar, options.tmin, options.tmax)))
    datasets = {v: reader.read(directories[v], PRODUCTS[v]) for v in VARIABLES}
    if datasets[VARIABLES[1]].station.fields["id"] != datasets[VARIABLES[2]].station.fields["id"]:
        raise InputError("Temperature station mismatch: V1 requires Tmax and Tmin from the same station")
    sources = {}
    for variable, dataset in datasets.items():
        first, last = dataset.observations.available
        if options.start_date < first or options.end_date > last:
            raise InputError(f"{variable}: requested training period {options.start_date} -> {options.end_date} outside available {first} -> {last}")
        sources[variable] = dataset.provenance()
    if len({d.observations.available for d in datasets.values()}) > 1:
        warn("Source date coverage differs; all sources cover the requested training period")
    joined = JoinedWeatherDataset.join([datasets[v].observations for v in VARIABLES]).training_period(options.start_date, options.end_date)
    for i, variable in enumerate(VARIABLES):
        observations = [r[i] for r in joined.rows.values()]
        absent = sum(o is None for o in observations)
        missing = sum(o is None or o.value is None for o in observations)
        flags = Counter(o.quality or "blank" for o in observations if o is not None) if datasets[variable].product.accumulation_column else Counter()
        sources[variable]["training_quality_counts"] = dict(sorted(flags.items()))
        sources[variable]["training_absent_date_count"] = absent
        if missing:
            warn(f"{variable}: {missing} missing training observations ({absent} absent CSV dates); retained as missing")
        unusual = {k: v for k, v in flags.items() if k != "Y"}
        if unusual:
            warn(f"{variable}: quality flags {unusual}; all numeric observations retained")
        accumulated = sum(o is not None and o.accumulation_days not in (None, 1) for o in observations)
        if accumulated:
            warn(f"{variable}: {accumulated} multi-day accumulation records retained as supplied")
    calibration = calibrate(joined)
    for m in calibration.dependence:
        if m["observation_count"] < 30:
            warn(f"Month {m['month']}: low complete-case count {m['observation_count']} (<30)")
    timestamp = datetime.now(timezone.utc).isoformat() if options.include_timestamp else None
    return datasets, WeatherModelBuilder.build(calibration, sources, {v: PRODUCTS[v].units for v in VARIABLES}, options.start_date, options.end_date, options.model_name, options.location_name, timestamp)


def main(argv=None):
    options = parser().parse_args(argv)
    if options.output.exists() and not options.overwrite:
        print(f"ERROR: output exists: {options.output}; use --overwrite to replace", file=sys.stderr)
        return 5
    try:
        datasets, model = run(options)
    except (InputError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except (CalibrationError, OverflowError) as exc:
        print(f"ERROR: calibration failed: {exc}", file=sys.stderr)
        return 4
    try:
        # Even explicit overwrite may not destroy a source file.
        if options.output.resolve() in {p for d in datasets.values() for p in (d.note_file, d.data_file)}:
            raise OSError("Output must not replace an input file")
        JsonWeatherModelWriter().write(model, options.output, options.overwrite)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot write {options.output}: {exc}", file=sys.stderr)
        return 5
    print(ImportReportWriter.render(datasets, model, options.output, options.verbose))
    return 0
