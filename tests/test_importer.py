import calendar
import contextlib
import csv
from datetime import date, timedelta
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bom_weather_import.bom import BomDatasetReader, BomNoteParser, PRODUCTS, station_id
from bom_weather_import.calibration import (MonthlyStatisticsCalculator, CorrelationCalculator,
    CorrelationMatrixValidator, CholeskyValidator, calibrate)
from bom_weather_import.cli import main
from bom_weather_import.data import (InputError, CalibrationError, WeatherObservation,
    WeatherSeries, JoinedWeatherDataset, VARIABLES)
from bom_weather_import.output import JsonWeatherModelWriter, WeatherModelDefinition

ROOT = Path(__file__).resolve().parents[1]


def fixture(root, variable="solar_exposure", station="012345", rows=None):
    product = PRODUCTS[variable]
    stem = f"{product.id}_{station}_1800"
    directory = root / stem
    directory.mkdir()
    note = directory / (stem + "_Note.txt")
    note.write_text(f"""Notes for Synthetic Climate Data
Product code: {product.id} reference: 123
** Station Details **
Bureau of Meteorology station number: {int(station)}
Station name: TEST STATION
Year site opened: 1900
Year site closed: 
Latitude (decimal degrees, south negative): -33.95
Longitude (decimal degrees, east positive): 151.17
Height of station above mean sea level (metres): 6
State: NSW
** Data File Format **
 6    Note measurement description (note units)
1) QUALITY FLAG DESCRIPTIONS
Y: accepted
N: not yet checked
2) GAPS AND MISSING DATA
Gaps can exist.
3) TIME
Dates as recorded.
""")
    data = directory / (stem + "_Data.csv")
    headers = ["Product code", "Bureau of Meteorology station number", "Year", "Month", "Day", product.value_column]
    if product.accumulation_column:
        headers += [product.accumulation_column, "Quality"]
    with data.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for d, value, quality in rows or [(date(2020, 1, 1), 1, "Y")]:
            row = [product.id, station, d.year, d.month, d.day, value]
            if product.accumulation_column:
                row += [1 if value != "" else "", quality]
            writer.writerow(row)
    return directory, note, data


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def read(self, directory, variable="solar_exposure"):
        return BomDatasetReader().read(directory, PRODUCTS[variable])

    def test_station_normalisation(self):
        for value in ("66037", "066037", " 066037 "):
            self.assertEqual(station_id(value), "066037")
        for value in ("-1", "1234567", "66.0", "", "abcdef"):
            with self.assertRaises(InputError):
                station_id(value)

    def test_note_metadata_and_csv_authority(self):
        directory, note, _ = fixture(self.root)
        station, metadata = BomNoteParser().parse(note)
        self.assertEqual(station.fields, {"id": "012345", "name": "TEST STATION", "opened_year": 1900, "latitude": -33.95, "longitude": 151.17, "elevation_metres": 6, "state": "NSW"})
        self.assertIn("not yet checked", metadata["quality_information"])
        self.assertEqual(metadata["source_units"], "note units")
        dataset = self.read(directory)
        self.assertEqual(dataset.metadata["source_units"], "MJ/m*m")
        self.assertEqual(dataset.metadata["note_units"], "note units")
        self.assertEqual(dataset.metadata["measurement_description"], PRODUCTS[VARIABLES[0]].value_column)

    def test_optional_metadata_absent(self):
        _, note, _ = fixture(self.root)
        note.write_text("Product code: IDCJAC0016\nBureau of Meteorology station number: 12345\nStation name: TEST\n")
        station, metadata = BomNoteParser().parse(note)
        self.assertEqual(station.fields, {"id": "012345", "name": "TEST"})
        self.assertNotIn("source_units", metadata)

    def test_discovery_fallback(self):
        directory, _, _ = fixture(self.root)
        renamed = directory.rename(self.root / "solar")
        self.assertEqual(self.read(renamed).station.fields["id"], "012345")

    def test_discovery_missing_ambiguous_and_non_directory(self):
        directory, note, data = fixture(self.root)
        with self.assertRaises(InputError): self.read(data)
        extra = directory / "extra_Note.txt"
        extra.write_text(note.read_text())
        with self.assertRaises(InputError): self.read(directory)
        extra.unlink()
        note.unlink()
        with self.assertRaises(InputError): self.read(directory)
        with self.assertRaises(InputError): self.read(self.root / "absent")

    def test_mismatched_pair(self):
        directory, _, data = fixture(self.root)
        data.rename(directory / "IDCJAC0016_054321_1800_Data.csv")
        with self.assertRaisesRegex(InputError, "filenames"): self.read(directory)

    def test_directory_identity(self):
        directory, _, _ = fixture(self.root)
        directory = directory.rename(self.root / "IDCJAC0016_054321_1800")
        with self.assertRaisesRegex(InputError, "directory/file"): self.read(directory)

    def test_wrong_product(self):
        directory, _, _ = fixture(self.root)
        with self.assertRaisesRegex(InputError, "expected product"): self.read(directory, "temperature_maximum")

    def test_note_identity_mismatch(self):
        directory, note, _ = fixture(self.root)
        original = note.read_text()
        for text in (original.replace("12345", "54321"), original.replace("IDCJAC0016", "IDCJAC0010")):
            note.write_text(text)
            with self.assertRaisesRegex(InputError, "Note identity mismatch"): self.read(directory)

    def test_all_products_missing_zero_quality(self):
        for variable in VARIABLES:
            with self.subTest(variable=variable):
                directory, _, _ = fixture(self.root, variable, rows=[(date(2020,1,1), "", ""), (date(2020,1,2), 0, "N"), (date(2020,1,3), 2.5, "X")])
                obs = list(self.read(directory, variable).observations.observations.values())
                self.assertIsNone(obs[0].value)
                self.assertEqual(obs[1].value, 0)
                self.assertEqual(obs[2].value, 2.5)
                self.assertEqual(obs[2].quality, None if variable == VARIABLES[0] else "X")

    def test_duplicate(self):
        directory, _, _ = fixture(self.root, rows=[(date(2020,1,1),1,"Y")]*2)
        with self.assertRaisesRegex(InputError, "Duplicate"): self.read(directory)

    def test_bad_csv_values_and_identity(self):
        directory, _, data = fixture(self.root)
        original = data.read_text()
        for old, new in (("2020,1,1,1", "2020,2,30,1"), ("2020,1,1,1", "2020,1,1,nan"), ("2020,1,1,1", "2020,1,1,inf"), ("2020,1,1,1", "2020,1,1,bad"), ("IDCJAC0016,012345", "IDCJAC0010,012345"), ("IDCJAC0016,012345", "IDCJAC0016,054321"), ("2020,1,1,1", "2020,1,1,1,extra"), ("2020,1,1,1", "2020,1,1")):
            with self.subTest(new=new):
                data.write_text(original.replace(old, new))
                with self.assertRaises(InputError): self.read(directory)
        data.write_text(original.replace("Daily global solar exposure (MJ/m*m)", "Unknown"))
        with self.assertRaisesRegex(InputError, "columns"): self.read(directory)

    def test_accumulation_validation(self):
        directory, _, data = fixture(self.root, "temperature_minimum")
        original = data.read_text()
        for value in ("0", "1.5", "oops"):
            data.write_text(original.replace(",1,Y", f",{value},Y"))
            with self.assertRaises(InputError): self.read(directory, "temperature_minimum")


class CalibrationTests(unittest.TestCase):
    def test_statistics(self):
        stats = MonthlyStatisticsCalculator.calculate([1., 2., 3., None])
        self.assertEqual(stats, {"observation_count": 3, "missing_count": 1, "mean": 2., "std_dev": 1., "observed_minimum": 1., "observed_maximum": 3.})
        for values in ([], [None], [1, None], [1, float("nan")]):
            with self.assertRaises(CalibrationError): MonthlyStatisticsCalculator.calculate(values)

    def test_join_filter_group_and_absent_dates(self):
        dates = [date(2019,1,1), date(2020,1,1), date(2020,1,3), date(2020,2,1)]
        s = WeatherSeries({d: WeatherObservation(d, float(i)) for i,d in enumerate(dates)})
        joined = JoinedWeatherDataset.join([s,s,s])
        self.assertEqual(len(joined.months()[1]), 3)
        selected = joined.training_period(date(2020,1,1), date(2020,1,3))
        self.assertEqual(len(selected.rows), 3)
        self.assertEqual(selected.rows[date(2020,1,2)], (None,)*3)
        self.assertEqual(selected.months()[1], [(1.,)*3, (None,)*3, (2.,)*3])
        with self.assertRaises(InputError): joined.training_period(date(2021,1,1),date(2020,1,1))

    def test_pearson(self):
        self.assertAlmostEqual(CorrelationCalculator.pearson([1,2,3], [3,2,1]), -1)
        self.assertAlmostEqual(CorrelationCalculator.pearson([-1,0,1], [1,-2,1]), 0)
        self.assertAlmostEqual(CorrelationCalculator.pearson([1,2,3], [2,4,6]), 1)
        for x,y in (([1], [2]), ([1,1],[2,3]), ([1,2],[1,2,3])):
            with self.assertRaises(CalibrationError): CorrelationCalculator.pearson(x,y)

    def test_complete_cases(self):
        rows = [(1,1,1), (1,-1,-1), (-1,1,-1), (-1,-1,1), (100,None,100)]
        count, matrix = CorrelationCalculator.calculate(rows)
        self.assertEqual(count, 4)
        self.assertEqual(matrix, [[1.,0.,0.], [0.,1.,0.], [0.,0.,1.]])
        self.assertEqual(MonthlyStatisticsCalculator.calculate([r[0] for r in rows])["mean"], 20)
        with self.assertRaises(CalibrationError): CorrelationCalculator.calculate([(1,None,2)])

    def test_matrix_failures(self):
        invalid = [[], [[1,0],[0,1]], [[1,0,0],[0,1,0],[0,0,float('nan')]],
                   [[1,.3,0],[.2,1,0],[0,0,1]], [[.9,0,0],[0,1,0],[0,0,1]],
                   [[1,1.1,0],[1.1,1,0],[0,0,1]], [[1,.9,.9],[.9,1,-.9],[.9,-.9,1]]]
        for matrix in invalid:
            with self.subTest(matrix=matrix):
                with self.assertRaises(CalibrationError): CorrelationMatrixValidator.validate(matrix)

    def test_cholesky_reconstruction_and_singular(self):
        matrix = [[1,.2,.3],[.2,1,.4],[.3,.4,1]]
        lower = CholeskyValidator.validate(matrix)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(sum(lower[i][k]*lower[j][k] for k in range(3)), matrix[i][j])
        for matrix in ([[1,1,1]]*3, [[1,1-1e-14,0],[1-1e-14,1,0],[0,0,1]]):
            CorrelationMatrixValidator.validate(matrix)
            with self.assertRaisesRegex(CalibrationError, "Cholesky"): CholeskyValidator.validate(matrix)

    def test_failure_context(self):
        rows = {date(2020,1,d): tuple(WeatherObservation(date(2020,1,d), float(d)) for _ in range(3)) for d in range(1,5)}
        with self.assertRaisesRegex(CalibrationError, "Month 1, complete-case count 4, matrix"):
            calibrate(JoinedWeatherDataset(rows))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Three years of daily rows. Four orthogonal vectors per month/year;
        # all later dates blank. January day 5 has extra solar only.
        vectors = [(1,1,1),(1,-1,-1),(-1,1,-1),(-1,-1,1)]
        self.directories = {}
        for i, variable in enumerate(VARIABLES):
            rows = []
            for year in (2019,2020,2021):
                for month in range(1,13):
                    for day in range(1,calendar.monthrange(year,month)[1]+1):
                        value = (vectors[day-1][i] + (10,20,30)[i]) if day <= 4 else ""
                        if month == 1 and day == 5 and i == 0: value = 20
                        rows.append((date(year,month,day), value, "N" if day==1 else "Y"))
            self.directories[variable] = fixture(self.root, variable, rows=rows)[0]
        self.output = self.root / "model.json"
        self.args = ["--solar",str(self.directories[VARIABLES[0]]), "--tmin",str(self.directories[VARIABLES[1]]), "--tmax",str(self.directories[VARIABLES[2]]), "--start-date","2020-01-01", "--end-date","2021-12-31", "--model-name","Test", "--location-name","Test Location", "--output",str(self.output)]

    def invoke(self, args=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(self.args if args is None else args)
        return code, out.getvalue(), err.getvalue()

    def test_end_to_end_expected_model_and_determinism(self):
        code, out, err = self.invoke()
        self.assertEqual(code, 0, err)
        original = self.output.read_bytes()
        model = json.loads(original)
        self.assertNotIn("simulation", model)
        self.assertEqual(model["name"], "Test")
        self.assertEqual(model["type"], "CorrelatedMonthlyWeather")
        self.assertEqual(model["location"], {"name":"Test Location"})
        self.assertEqual(model["training_period"], {"start":"2020-01-01", "end":"2021-12-31"})
        self.assertEqual(model["dependence_model"]["variables"], list(VARIABLES))
        for i, variable in enumerate(VARIABLES):
            self.assertEqual(model[variable]["distribution"], "normal")
            self.assertEqual(model[variable]["units"], "MJ/m2/day" if i==0 else "C")
            self.assertEqual(len(model[variable]["monthly"]), 12)
            for month, stats in enumerate(model[variable]["monthly"],1):
                count = 10 if i==0 and month==1 else 8
                self.assertEqual(stats["observation_count"], count)
                days = sum(calendar.monthrange(y,month)[1] for y in (2020,2021))
                self.assertEqual(stats["missing_count"], days-count)
                self.assertAlmostEqual(stats["mean"], 12 if i==0 and month==1 else (10,20,30)[i])
                self.assertAlmostEqual(stats["std_dev"], math.sqrt(168/9) if i==0 and month==1 else math.sqrt(8/7))
            self.assertNotIn("latitude", model["location"])
        expected = [{"month":m,"observation_count":8,"correlation_matrix":[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]} for m in range(1,13)]
        self.assertEqual(model["dependence_model"]["monthly"], expected)
        self.assertIn("Cholesky validation: 12/12 passed",out)
        self.assertIn("WARNING",err)
        self.assertEqual(self.invoke()[0],5)
        self.assertEqual(self.output.read_bytes(),original)
        self.assertEqual(self.invoke(self.args+["--overwrite"])[0],0)
        self.assertEqual(self.output.read_bytes(),original)
        self.assertEqual(self.invoke(self.args+["--overwrite", "--include-timestamp"])[0],0)
        self.assertIn("generation_timestamp",json.loads(self.output.read_text()))

    def test_cli_subprocess(self):
        result = subprocess.run([sys.executable,"-m","bom_weather_import",*self.args],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(self.output.exists())
        result = subprocess.run([str(ROOT/"bom-weather-import"),"--start-date","20200230"],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)

    def test_coverage_and_inverted_period(self):
        for old,new in (("2020-01-01","2018-01-01"),("2021-12-31","2022-01-01"),("2020-01-01","2022-01-01")):
            args = [new if a==old else a for a in self.args]
            self.assertEqual(self.invoke(args)[0],3)
        self.assertFalse(self.output.exists())

    def test_temperature_station_mismatch(self):
        other = fixture(self.root, "temperature_minimum",station="054321")[0]
        args = [str(other) if a == str(self.directories[VARIABLES[1]]) else a for a in self.args]
        code, _, err = self.invoke(args)
        self.assertEqual(code,3)
        self.assertIn("Temperature station mismatch",err)

    def test_calibration_exit_and_no_output(self):
        for variable in VARIABLES:
            data = next(self.directories[variable].glob("*_Data.csv"))
            with data.open() as stream:
                rows = list(csv.reader(stream))
            for row in rows[1:]:
                if row[5]: row[5] = "1"
            with data.open("w",newline="") as stream: csv.writer(stream).writerows(rows)
        code, _, err = self.invoke()
        self.assertEqual(code,4)
        self.assertIn("zero-variance",err)
        self.assertFalse(self.output.exists())

    def test_output_error_and_source_protection(self):
        args = [str(self.root/"absent"/"model.json") if a==str(self.output) else a for a in self.args]
        self.assertEqual(self.invoke(args)[0],5)
        source = next(self.directories[VARIABLES[0]].glob("*_Data.csv"))
        before = source.read_bytes()
        args = [str(source) if a==str(self.output) else a for a in self.args]+["--overwrite"]
        self.assertEqual(self.invoke(args)[0],5)
        self.assertEqual(source.read_bytes(),before)


class WriterTests(unittest.TestCase):
    def test_known_json_and_no_nan(self):
        writer = JsonWeatherModelWriter()
        model = WeatherModelDefinition({"name":"Test", "value":1.25})
        self.assertEqual(writer.render(model), '{\n  "name": "Test",\n  "value": 1.25\n}\n')
        with self.assertRaises(ValueError): writer.render(WeatherModelDefinition({"value":float("nan")}))


if __name__ == "__main__":
    unittest.main()
