"""Normalised observations and date joining, independent of file formats."""
from dataclasses import dataclass
from datetime import date, timedelta

VARIABLES = ("solar_exposure", "temperature_minimum", "temperature_maximum")


class InputError(ValueError):
    pass


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class WeatherObservation:
    date: date
    value: float | None
    quality: str | None = None
    accumulation_days: int | None = None


@dataclass
class WeatherSeries:
    observations: dict[date, WeatherObservation]

    @property
    def available(self):
        return min(self.observations), max(self.observations)


@dataclass
class JoinedWeatherDataset:
    rows: dict[date, tuple[WeatherObservation | None, ...]]

    @classmethod
    def join(cls, series):
        dates = sorted(set().union(*(s.observations for s in series)))
        return cls({d: tuple(s.observations.get(d) for s in series) for d in dates})

    def training_period(self, start, end):
        if start > end:
            raise InputError("Training start must be on or before end")
        # Explicitly represent absent calendar dates as missing, too.
        return JoinedWeatherDataset({start + timedelta(days=i): self.rows.get(
            start + timedelta(days=i), (None,) * len(VARIABLES))
            for i in range((end - start).days + 1)})

    def months(self):
        return {m: [tuple(o.value if o else None for o in row)
                    for d, row in sorted(self.rows.items()) if d.month == m]
                for m in range(1, 13)}
