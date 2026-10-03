"""Acceptance checks against supplied CSVs, independent of importer parsers/statistics."""
import calendar
import csv
from datetime import date
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ("solar_exposure", "IDCJAC0016_066006_1800", "Daily global solar exposure (MJ/m*m)"),
    ("temperature_minimum", "IDCJAC0011_066037_1800", "Minimum temperature (Degree C)"),
    ("temperature_maximum", "IDCJAC0010_066037_1800", "Maximum temperature (Degree C)"),
)


class RealDataAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series = {}
        for variable, stem, column in SOURCES:
            with (ROOT / "inputs" / stem / (stem + "_Data.csv")).open(newline="") as stream:
                cls.series[variable] = {date(int(r["Year"]), int(r["Month"]), int(r["Day"])): float(r[column]) if r[column] else None for r in csv.DictReader(stream)}

    def test_all_generated_statistics_and_correlations(self):
        for start in (1990, 2016):
            with self.subTest(start=start):
                model = json.loads((ROOT / "outputs" / f"weather_model_066006_066037_{start}_2025.json").read_text())
                for month in range(1,13):
                    selected = {v: {d:x for d,x in series.items() if start <= d.year <= 2025 and d.month == month} for v,series in self.series.items()}
                    for variable, values in selected.items():
                        valid = [x for x in values.values() if x is not None]
                        mean = math.fsum(valid)/len(valid)
                        sd = math.sqrt(math.fsum((x-mean)**2 for x in valid)/(len(valid)-1))
                        stats = model[variable]["monthly"][month-1]
                        self.assertEqual(stats["observation_count"],len(valid))
                        self.assertEqual(stats["missing_count"],sum(calendar.monthrange(y,month)[1] for y in range(start,2026))-len(valid))
                        self.assertAlmostEqual(stats["mean"],mean,places=12)
                        self.assertAlmostEqual(stats["std_dev"],sd,places=12)
                        self.assertEqual(stats["observed_minimum"], min(valid))
                        self.assertEqual(stats["observed_maximum"], max(valid))
                    matched = sorted(set.intersection(*({d for d,x in s.items() if x is not None} for s in selected.values())))
                    vectors = [[selected[v][d] for d in matched] for v,_,_ in SOURCES]
                    means = [math.fsum(v)/len(v) for v in vectors]
                    covariance = [[math.fsum((x-means[i])*(y-means[j]) for x,y in zip(vectors[i],vectors[j]))/(len(matched)-1) for j in range(3)] for i in range(3)]
                    dep = model["dependence_model"]["monthly"][month-1]
                    self.assertEqual(dep["observation_count"],len(matched))
                    for i in range(3):
                        for j in range(3):
                            expected = covariance[i][j]/math.sqrt(covariance[i][i]*covariance[j][j])
                            self.assertAlmostEqual(dep["correlation_matrix"][i][j],expected,places=12)
                    r12,r13,r23 = dep["correlation_matrix"][0][1],dep["correlation_matrix"][0][2],dep["correlation_matrix"][1][2]
                    self.assertGreater(1+2*r12*r13*r23-r12*r12-r13*r13-r23*r23, 0)

    def test_real_cli_byte_reproducibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            for start,name in ((1990,"SydneyWeatherLongTerm"),(2016,"SydneyWeatherRecent")):
                output = Path(temporary)/f"{start}.json"
                args = [sys.executable,"-m","bom_weather_import", "--start-date",f"{start}-01-01", "--end-date","2025-12-31", "--model-name",name, "--location-name","Sydney", "--output",str(output)]
                for flag,(_,stem,_) in zip(("--solar","--tmin","--tmax"),SOURCES):
                    args += [flag,str(ROOT/"inputs"/stem)]
                result = subprocess.run(args,cwd=ROOT,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(output.read_bytes(), (ROOT/"outputs"/f"weather_model_066006_066037_{start}_2025.json").read_bytes())
