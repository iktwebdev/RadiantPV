"""Statistics on normalised daily values; no BOM syntax or file dependencies."""
import math
import statistics
from dataclasses import dataclass
from itertools import combinations

from .data import CalibrationError, VARIABLES

TOLERANCE = 1e-12


class MonthlyStatisticsCalculator:
    @staticmethod
    def calculate(values):
        valid = [v for v in values if v is not None]
        if len(valid) < 2:
            raise CalibrationError(f"Sample standard deviation requires at least two valid observations; got {len(valid)}")
        if not all(math.isfinite(v) for v in valid):
            raise CalibrationError("Non-finite observation")
        return {"observation_count": len(valid), "missing_count": len(values) - len(valid),
                "mean": statistics.mean(valid), "std_dev": statistics.stdev(valid),
                "observed_minimum": min(valid), "observed_maximum": max(valid)}


class CorrelationCalculator:
    @staticmethod
    def pearson(x, y):
        if len(x) != len(y) or len(x) < 2:
            raise CalibrationError("Pearson correlation requires at least two matched observations")
        mx, my = statistics.mean(x), statistics.mean(y)
        dx, dy = [v - mx for v in x], [v - my for v in y]
        sx, sy = math.fsum(v*v for v in dx), math.fsum(v*v for v in dy)
        if sx <= 0 or sy <= 0:
            raise CalibrationError("Pearson correlation undefined for zero-variance complete-case variable")
        # No clipping or matrix repair; validators reject invalid results.
        return math.fsum(a*b for a, b in zip(dx, dy)) / (math.sqrt(sx) * math.sqrt(sy))

    @classmethod
    def calculate(cls, rows):
        complete = [r for r in rows if all(v is not None for v in r)]
        if len(complete) < 2:
            raise CalibrationError(f"Insufficient complete-case observations: {len(complete)}")
        columns = list(zip(*complete))
        matrix = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
        for i, j in combinations(range(3), 2):
            matrix[i][j] = matrix[j][i] = cls.pearson(columns[i], columns[j])
        return len(complete), matrix


class CorrelationMatrixValidator:
    @staticmethod
    def validate(matrix):
        if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
            raise CalibrationError("Correlation matrix must be 3x3")
        for i in range(3):
            for j in range(3):
                value = matrix[i][j]
                if not math.isfinite(value):
                    raise CalibrationError("Correlation matrix contains non-finite values")
                if not -1 <= value <= 1:
                    raise CalibrationError("Correlation coefficient outside [-1,1]")
                if abs(value - matrix[j][i]) > TOLERANCE:
                    raise CalibrationError("Correlation matrix is not symmetric")
            if abs(matrix[i][i] - 1) > TOLERANCE:
                raise CalibrationError("Correlation matrix must have unit diagonal")
        # For a real symmetric 3x3 matrix, nonnegative ALL principal minors
        # (not merely leading minors) are necessary and sufficient for PSD.
        for i, j in combinations(range(3), 2):
            if matrix[i][i]*matrix[j][j] - matrix[i][j]*matrix[j][i] < -TOLERANCE:
                raise CalibrationError("Correlation matrix is not positive semidefinite")
        a, b, c = matrix
        determinant = (a[0]*(b[1]*c[2]-b[2]*c[1]) - a[1]*(b[0]*c[2]-b[2]*c[0]) + a[2]*(b[0]*c[1]-b[1]*c[0]))
        if determinant < -TOLERANCE:
            raise CalibrationError(f"Correlation matrix is not positive semidefinite (determinant={determinant})")


class CholeskyValidator:
    @staticmethod
    def validate(matrix):
        CorrelationMatrixValidator.validate(matrix)
        lower = [[0.0]*3 for _ in range(3)]
        for i in range(3):
            for j in range(i+1):
                residual = matrix[i][j] - math.fsum(lower[i][k]*lower[j][k] for k in range(j))
                if i == j:
                    if residual <= TOLERANCE:
                        raise CalibrationError(f"Cholesky failed at pivot {i}: {residual}; singular, numerically singular or not positive definite")
                    lower[i][j] = math.sqrt(residual)
                else:
                    lower[i][j] = residual / lower[j][j]
        for i in range(3):
            for j in range(3):
                if abs(math.fsum(lower[i][k]*lower[j][k] for k in range(3)) - matrix[i][j]) > TOLERANCE:
                    raise CalibrationError("Cholesky reconstruction failed")
        return lower


@dataclass
class MonthlyCalibration:
    statistics: dict
    dependence: list


def calibrate(joined):
    stats = {v: [] for v in VARIABLES}
    dependence = []
    for month, rows in joined.months().items():
        for i, variable in enumerate(VARIABLES):
            try:
                stats[variable].append({"month": month, **MonthlyStatisticsCalculator.calculate([r[i] for r in rows])})
            except CalibrationError as exc:
                raise CalibrationError(f"Month {month}, {variable}: {exc}") from exc
        count = sum(all(v is not None for v in r) for r in rows)
        matrix = None
        try:
            count, matrix = CorrelationCalculator.calculate(rows)
            CorrelationMatrixValidator.validate(matrix)
            CholeskyValidator.validate(matrix)
        except CalibrationError as exc:
            raise CalibrationError(f"Month {month}, complete-case count {count}, matrix {matrix}: {exc}") from exc
        dependence.append({"month": month, "observation_count": count, "correlation_matrix": matrix})
    return MonthlyCalibration(stats, dependence)
