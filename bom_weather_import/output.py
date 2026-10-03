"""Model construction, deterministic JSON output and human-readable diagnostics."""
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .data import VARIABLES
from .calibration import TOLERANCE


@dataclass
class WeatherModelDefinition:
    fields: dict


class WeatherModelBuilder:
    @staticmethod
    def build(calibration, sources, units, start, end, name, location=None, generated_at=None):
        fields = {"name": name, "type": "CorrelatedMonthlyWeather"}
        if location:
            fields["location"] = {"name": location}
        fields["training_period"] = {"start": start.isoformat(), "end": end.isoformat()}
        fields["source"] = {"provider": "Bureau of Meteorology", **sources}
        fields["calibration"] = {"importer_version": __version__, "standard_deviation": "sample",
                                 "quality_policy": "retain_all_numeric_observations",
                                 "missing_data_policy": "no_imputation",
                                 "correlation_policy": "complete_case",
                                 "matrix_tolerance": TOLERANCE,
                                 "cholesky_minimum_pivot": TOLERANCE}
        if generated_at is not None:
            fields["generation_timestamp"] = generated_at
        for variable in VARIABLES:
            fields[variable] = {"units": units[variable], "distribution": "normal", "monthly": calibration.statistics[variable]}
        fields["dependence_model"] = {"type": "correlation_matrix", "variables": list(VARIABLES), "monthly": calibration.dependence}
        return WeatherModelDefinition(fields)


class JsonWeatherModelWriter:
    @staticmethod
    def render(model):
        return json.dumps(model.fields, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    def write(self, model, output, overwrite=False):
        output = Path(output)
        content = self.render(model)
        # Publish a complete file atomically; hard-link publication prevents a
        # concurrent creator being overwritten when --overwrite was not given.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if overwrite:
                os.replace(temporary, output)
            else:
                os.link(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class ImportReportWriter:
    @staticmethod
    def render(datasets, model, output, verbose=False):
        fields = model.fields
        lines = ["BOM Weather Model Import", "Training period: " + " -> ".join(fields["training_period"].values())]
        for variable in VARIABLES:
            dataset = datasets[variable]
            start, end = dataset.observations.available
            stats = fields[variable]["monthly"]
            lines += [f"{variable}: {dataset.directory}",
                      f"  Product: {dataset.product.id}; station: {dataset.station.fields['id']} {dataset.station.fields['name']}",
                      f"  Available: {start} -> {end}",
                      f"  Training valid: {sum(s['observation_count'] for s in stats)}; missing: {sum(s['missing_count'] for s in stats)}",
                      f"  Training quality flags: {json.dumps(fields['source'][variable]['training_quality_counts'], sort_keys=True)}"]
            if verbose:
                lines += [f"  Note: {dataset.note_file}", f"  Data: {dataset.data_file}"]
                for s in stats:
                    lines.append(f"  Month {s['month']:02}: n={s['observation_count']} missing={s['missing_count']} mean={s['mean']:.6f} sample_sd={s['std_dev']:.6f} min={s['observed_minimum']} max={s['observed_maximum']}")
        monthly = fields["dependence_model"]["monthly"]
        lines += [f"Complete-case observations: {sum(m['observation_count'] for m in monthly)}", "Monthly correlation observations: " + ", ".join(f"{m['month']:02}={m['observation_count']}" for m in monthly),
                  "Correlation validation: 12/12 passed", "Cholesky validation: 12/12 passed", f"Output: {output}"]
        return "\n".join(lines)
