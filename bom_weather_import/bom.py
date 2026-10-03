"""BOM directory identity, Note metadata and product-specific CSV schemas."""
import csv
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .data import InputError, WeatherObservation, WeatherSeries


@dataclass(frozen=True)
class Product:
    id: str
    variable: str
    value_column: str
    units: str
    accumulation_column: str | None = None


PRODUCTS = {
    "solar_exposure": Product("IDCJAC0016", "solar_exposure", "Daily global solar exposure (MJ/m*m)", "MJ/m2/day"),
    "temperature_minimum": Product("IDCJAC0011", "temperature_minimum", "Minimum temperature (Degree C)", "C", "Days of accumulation of minimum temperature"),
    "temperature_maximum": Product("IDCJAC0010", "temperature_maximum", "Maximum temperature (Degree C)", "C", "Days of accumulation of maximum temperature"),
}
IDENTITY = re.compile(r"(IDCJAC\d{4})_(\d{6})_([A-Za-z0-9-]+)")


def station_id(value):
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,6}", value):
        raise InputError(f"Invalid BOM station ID: {value!r}")
    return value.zfill(6)


def finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite number: {value!r}")
    return number


@dataclass
class BomStationMetadata:
    fields: dict


class BomNoteParser:
    def parse(self, path):
        text = Path(path).read_text(encoding="utf-8-sig")
        fields = dict(re.findall(r"^([^:\n]+):[ \t]*(.*)$", text, re.MULTILINE))
        try:
            station = {"id": station_id(fields["Bureau of Meteorology station number"]),
                       "name": fields["Station name"].strip()}
            if not station["name"]:
                raise ValueError("Empty station name")
            product_match = re.fullmatch(r"(IDCJAC\d{4})(?:\s+reference:\s*(\S+))?", fields["Product code"].strip())
            if not product_match:
                raise ValueError("Invalid product code")
            for label, key in (("Latitude (decimal degrees, south negative)", "latitude"),
                               ("Longitude (decimal degrees, east positive)", "longitude"),
                               ("Height of station above mean sea level (metres)", "elevation_metres")):
                if fields.get(label, "").strip():
                    station[key] = finite_number(fields[label])
            for key, limit in (("latitude", 90), ("longitude", 180)):
                if key in station and abs(station[key]) > limit:
                    raise ValueError(f"Invalid {key}")
            for label, key in (("Year site opened", "opened_year"), ("Year site closed", "closed_year")):
                if fields.get(label, "").strip():
                    year = int(fields[label])
                    if not 1 <= year <= 9999:
                        raise ValueError(f"Invalid {label}")
                    station[key] = year
            if fields.get("State", "").strip():
                station["state"] = fields["State"].strip()
        except (KeyError, ValueError) as exc:
            raise InputError(f"{path}: invalid Note metadata: {exc}") from exc
        metadata = {"product": product_match[1]}
        if product_match[2]:
            metadata["reference"] = product_match[2]
        description = re.search(r"^Notes for (.+)$", text, re.MULTILINE)
        if description:
            metadata["description"] = description[1].strip()
        columns = dict(re.findall(r"^\s*(\d+)\s+([^\n]+)$", text, re.MULTILINE))
        if "6" in columns:
            metadata["measurement_description"] = columns["6"].strip()
            unit = re.search(r"\(([^)]+)\)$", columns["6"].strip())
            if unit:
                metadata["source_units"] = unit[1]
        for heading, key in (("QUALITY FLAG DESCRIPTIONS", "quality_information"), ("GAPS AND MISSING DATA", "missing_data_information"), ("TIME", "time_information")):
            match = re.search(r"\d+\)\s*" + heading + r"\s*\n(.*?)(?=\n\d+\)|\Z)", text, re.DOTALL)
            if match:
                metadata[key] = " ".join(match[1].split())
        satellite = re.search(r"Global solar exposure data in this product.*?(?=\n\n)", text, re.DOTALL)
        if satellite:
            metadata["measurement_information"] = " ".join(satellite[0].split())
        created = re.search(r"^Created on (.+)$", text, re.MULTILINE)
        if created:
            metadata["export_creation_information"] = created[1].strip()
        return BomStationMetadata(station), metadata


class BomDataParser:
    def parse(self, path, product, station):
        common = ["Product code", "Bureau of Meteorology station number", "Year", "Month", "Day"]
        expected = common + [product.value_column]
        if product.accumulation_column:
            expected += [product.accumulation_column, "Quality"]
        observations = {}
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames) or set(reader.fieldnames) != set(expected):
                raise InputError(f"{path}: unrecognised {product.id} CSV columns: {reader.fieldnames}; expected {expected}")
            try:
                for row in reader:
                    try:
                        if None in row or any(v is None for v in row.values()):
                            raise ValueError("Incorrect number of CSV fields")
                        row = {k: v.strip() for k, v in row.items()}
                        if row["Product code"] != product.id or station_id(row[common[1]]) != station:
                            raise ValueError("CSV product/station identity mismatch")
                        d = date(*(int(row[k]) for k in ("Year", "Month", "Day")))
                        if d in observations:
                            raise ValueError(f"Duplicate observation for {station}/{product.variable}/{d}")
                        value = finite_number(row[product.value_column]) if row[product.value_column] else None
                        accumulation = None
                        if product.accumulation_column and row[product.accumulation_column]:
                            accumulation = int(row[product.accumulation_column])
                            if accumulation < 1:
                                raise ValueError("Accumulation days must be positive")
                        observations[d] = WeatherObservation(d, value, row.get("Quality") or None, accumulation)
                    except ValueError as exc:
                        raise InputError(f"{path}:{reader.line_num}: {exc}") from exc
            except csv.Error as exc:
                raise InputError(f"{path}:{reader.line_num}: invalid CSV: {exc}") from exc
        if not observations:
            raise InputError(f"{path}: no observations")
        return WeatherSeries(dict(sorted(observations.items())))


@dataclass
class BomDataset:
    directory: Path
    note_file: Path
    data_file: Path
    station: BomStationMetadata
    product: Product
    metadata: dict
    observations: WeatherSeries
    hashes: dict

    def provenance(self):
        start, end = self.observations.available
        return {**self.metadata, "station": self.station.fields,
                "available_period": {"start": start.isoformat(), "end": end.isoformat()},
                "files": {"note": self.note_file.name, "data": self.data_file.name},
                "sha256": self.hashes}


class BomDatasetReader:
    def read(self, directory, expected_product):
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise InputError(f"BOM input must be an existing dataset directory: {directory}")
        notes, data = sorted(directory.glob("*_Note.txt")), sorted(directory.glob("*_Data.csv"))
        if len(notes) != 1 or len(data) != 1 or not notes[0].is_file() or not data[0].is_file():
            raise InputError(f"{directory}: expected exactly one Note/Data pair; found {len(notes)} Note and {len(data)} Data files")
        stem = notes[0].name.removesuffix("_Note.txt")
        identity = IDENTITY.fullmatch(stem)
        if not identity or data[0].name != stem + "_Data.csv":
            raise InputError(f"{directory}: mismatched or invalid dataset filenames")
        directory_identity = IDENTITY.fullmatch(directory.name)
        if directory_identity and directory.name != stem:
            raise InputError(f"{directory}: directory/file dataset identity mismatch")
        if identity[1] != expected_product.id:
            raise InputError(f"{directory}: expected product {expected_product.id}, got {identity[1]}")
        station, metadata = BomNoteParser().parse(notes[0])
        if station.fields["id"] != identity[2] or metadata["product"] != identity[1]:
            raise InputError(f"{directory}: dataset/Note identity mismatch: filename {(identity[1], identity[2])}, Note {metadata['product']}/{station.fields['id']}")
        # CSV schema is authoritative; Note descriptions remain source provenance.
        if "measurement_description" in metadata:
            metadata["note_measurement_description"] = metadata.pop("measurement_description")
        if "source_units" in metadata:
            metadata["note_units"] = metadata.pop("source_units")
        metadata["measurement_description"] = expected_product.value_column
        metadata["source_units"] = re.search(r"\(([^)]+)\)$", expected_product.value_column)[1]
        metadata["dataset_suffix"] = identity[3]
        observations = BomDataParser().parse(data[0], expected_product, identity[2])
        hashes = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in (("note", notes[0]), ("data", data[0]))}
        return BomDataset(directory, notes[0], data[0], station, expected_product, metadata, observations, hashes)
