# PV Simulator V1 - Engine Implementation Specification

## 1. Purpose

Implement a deterministic, multithreaded Monte Carlo simulation engine suitable for modelling rooftop photovoltaic installations.

Version 1 shall implement:

- A generic Monte Carlo simulation engine.
- A fixed scenario/time/value simulation matrix.
- Deterministic scenario-specific random number generation.
- Parallel execution over independent scenarios.
- Configurable timestep definitions.
- Weather models.
- PV panel models.
- PV degradation models.
- PV arrays and installations.
- PV system losses.
- Configurable outputs.
- JSON input.
- CSV output.

The engine must be designed as a **generic simulation framework**, not as a PV-specific execution engine.

PV is the first application of the framework.

Future versions must be able to add models such as:

- inflation;
- interest rates;
- electricity prices;
- tariffs;
- household load;
- batteries;
- battery degradation;
- component failures;
- maintenance;
- rainfall;
- weather regime models;
- economic cashflows;
- NPV and IRR calculations.

These future features must not require redesigning the simulation kernel.

---

# 2. Fundamental Simulation Model

The simulation state is represented by:

\[
V[s,t,v]
\]

where:

- `s` = scenario;
- `t` = timestep;
- `v` = registered simulation value.

The complete simulation matrix shall be allocated before scenario execution begins.

Conceptually:

```text
Scenario 0
    Timestep 0
        Value 0
        Value 1
        ...
    Timestep 1
        Value 0
        Value 1
        ...

Scenario 1
    ...
```

The preferred physical representation is one contiguous block of doubles.

The matrix index is:

```cpp
index = ((scenario * numTimesteps) + timestep) * numValues + valueIndex;
```

Equivalent:

```cpp
index =
    scenario * timestepValueProduct +
    timestep * numValues +
    valueIndex;
```

where:

```cpp
timestepValueProduct = numTimesteps * numValues;
```

The value dimension shall be contiguous.

This is intentional because the normal execution order will be:

```text
scenario
    timestep
        model
            values
```

and therefore values associated with the current scenario/timestep should have good locality.

---

# 3. Scenario Is a Simulation Dimension; Thread Is Not

The matrix shall be indexed by:

```text
Scenario
Timestep
Value
```

It shall **not** be indexed by thread.

Thread ownership is purely an execution concern.

This distinction is important.

The same simulation run with:

```json
"threads": 1
```

and:

```json
"threads": 16
```

must produce identical scenario results.

---

# 4. Value Types

## 4.1 Global ValueType enumeration

Simulation values shall be represented internally using an enumeration.

Example:

```cpp
enum class ValueType : uint16_t
{
    SolarExposure = 0,
    TemperatureMaximum,
    TemperatureMinimum,

    PVGenerationKWh,
    DegradationFactor,

    // Future examples:
    InflationRate,
    InflationIndex,
    ShortRate,
    ElectricityPrice,
    NetCashflow,

    Count
};
```

The exact initial V1 list should be derived from the implemented V1 models.

Enumeration members describe the **semantic meaning of a value**, not merely its unit.

For example:

```text
PVGenerationKWh
GridImportKWh
GridExportKWh
BatteryChargeKWh
```

are different `ValueType`s even though all are measured in kWh.

Do not define a generic `KWh` value type.

---

## 4.2 External names

JSON configuration shall use human-readable names such as:

```json
"solar_exposure"
"temperature_maximum"
"temperature_minimum"
"pv_generation_kwh"
"degradation_factor"
```

During configuration loading these strings shall be converted to `ValueType`.

No string lookup should occur in the scenario execution hot path.

There should be a central bidirectional registry:

```text
string -> ValueType
ValueType -> string
```

Unknown value names must cause configuration validation failure.

---

## 4.3 Dense matrix mapping

The global `ValueType` enumeration may eventually contain hundreds of possible values.

A particular simulation may only require a subset.

Therefore construct a simulation-specific mapping:

```text
ValueType -> matrix value index
```

For example:

```text
SolarExposure          enum 0   -> v=0
TemperatureMaximum     enum 1   -> v=1
TemperatureMinimum     enum 2   -> v=2
PVGenerationKWh        enum 8   -> v=3
DegradationFactor      enum 12  -> v=4
```

The simulation matrix therefore allocates only the values required by the current simulation.

The resulting matrix is dense in `v`, although many `[s,t,v]` cells may never be populated.

Do not implement a genuinely sparse matrix for V1.

---

# 5. SimulationValueMatrix

Implement a class responsible for storage and access to the simulation cube.

Suggested interface:

```cpp
class SimulationValueMatrix
{
public:
    void Allocate(
        size_t scenarios,
        size_t timesteps,
        const std::vector<ValueType>& valueTypes);

    void SetValue(
        size_t scenario,
        size_t timestep,
        ValueType valueType,
        double value);

    double GetValue(
        size_t scenario,
        size_t timestep,
        ValueType valueType) const;

    size_t GetValueIndex(ValueType valueType) const;

    size_t ScenarioCount() const;
    size_t TimestepCount() const;
    size_t ValueCount() const;
};
```

Internally:

```cpp
std::vector<double> values;
```

or an equivalent contiguous allocation.

The hot-path implementation should resolve the value type to its dense matrix index and perform simple index arithmetic.

Avoid:

- maps;
- strings;
- locks;
- virtual dispatch inside matrix access;
- per-value heap allocation.

A debug build may initialise matrix cells to `NaN` so that reads of uninitialised values can be detected.

Release builds do not need to pay this initialisation cost unless required.

---

# 6. Dimension / Simulation Context

Models need to know which scenario and timestep they are executing.

A lightweight context structure should be provided.

For example:

```cpp
struct SimulationContext
{
    size_t Scenario;
    size_t TimeStep;

    double Dt;
    double ElapsedYears;

    SimulationValueMatrix* Values;
    RandomGenerator* Random;
};
```

Thread ID should not normally be required by a model.

If it is needed for diagnostics, it may be present as execution metadata, but models must not use thread ID as part of their mathematical state.

The old engine's `Dimension(TimeStep, Scenario, ThreadId)` concept can therefore be simplified.

---
# 6b. Scenario Shocks

Each model may require zero or more stochastic shocks, denoted \(dZ\).

Shock generation is a simulation-level service. Individual models shall not independently create their own random number generators or perform their own correlation calculations.

This allows stochastic variables belonging to different models to participate in a common correlation structure.

For each scenario and timestep, shocks are generated through the following pipeline:

```text
Scenario RNG
    |
    v
Independent U(0,1) random values
    |
    v
Inverse Normal CDF
    |
    v
Independent N(0,1) shocks
    |
    v
Cholesky transformation
    |
    v
Correlated N(0,1) shocks
    |
    v
DZ Cache
    |
    v
Models
```

## 6b.1 Shock Registration

Each model shall declare the stochastic shocks it requires during initialisation.

A model may require:

```text
0 shocks
1 shock
N shocks
```

Examples:

```text
PV degradation model
    0 shocks              [deterministic V1 model]

Weather model
    SolarExposure
    TemperatureMinimum
    TemperatureMaximum

Future Vasicek model
    ShortRate

Future inflation model
    InflationRate
```

Each shock shall have a globally unique identifier.

Conceptually:

```text
SydneyWeatherRecent.SolarExposure
SydneyWeatherRecent.TemperatureMinimum
SydneyWeatherRecent.TemperatureMaximum
AustralianEconomy.Inflation
AustralianEconomy.ShortRate
```

During initialisation these identifiers are resolved to integer shock indices:

```text
SydneyWeatherRecent.SolarExposure          -> dZ 0
SydneyWeatherRecent.TemperatureMinimum      -> dZ 1
SydneyWeatherRecent.TemperatureMaximum      -> dZ 2
```

Strings shall not be used to identify shocks during scenario execution.

The engine should maintain a `ShockRegistry` analogous to the `ValueTypeRegistry`.

---

## 6b.2 Scenario RNG

Each scenario has its own deterministic Mersenne Twister random number stream.

The RNG is initialised once at the beginning of the scenario using the scenario number.

The required seeding procedure is:

```cpp
rng.Seed(scenarioNumber);

uint32_t intermediateSeed = rng.NextUInt();

rng.Seed(intermediateSeed);
```

All random numbers required by that scenario are then drawn sequentially from this RNG.

The RNG belongs logically to the scenario, not to the worker thread.

Therefore:

```text
Scenario 786 on Thread 0
```

must receive exactly the same random sequence as:

```text
Scenario 786 on Thread 7
```

Changing the number of worker threads must not change any generated shocks.

---

## 6b.3 Independent Uniform Random Values

For every registered shock required at timestep \(t\), generate one independent pseudo-random uniform value:

\[
U_i \sim U(0,1)
\]

where:

\[
i=0,\ldots,N_{dZ}-1
\]

and \(N_{dZ}\) is the number of registered stochastic shocks.

The order in which RNG values are consumed must be deterministic.

The `ShockRegistry` shall therefore establish a fixed shock ordering during simulation initialisation.

The scenario execution must always generate shocks in this order.

Model execution order must not affect RNG consumption.

This is important. A model should not call the scenario RNG directly when it happens to need a random number, because adding or reordering models would then change the random streams seen by unrelated models.

Instead, the shock subsystem generates the complete shock vector for the timestep before stochastic models consume it.

---

## 6b.4 Conversion to Independent Standard Normal Shocks

Each uniform random value is converted to a standard normal variate using the inverse standard normal cumulative distribution function:

\[
Z_i=\Phi^{-1}(U_i)
\]

where:

\[
Z_i\sim N(0,1)
\]

The resulting vector:

\[
Z=
\begin{bmatrix}
Z_1\\
Z_2\\
\vdots\\
Z_n
\end{bmatrix}
\]

contains independent standard normal shocks.

The inverse-normal implementation must be deterministic.

Care must be taken that the uniform RNG cannot result in an invalid input at exactly 0 or 1 for the inverse CDF. The RNG/conversion layer shall define and test the handling of these endpoints.

---

## 6b.5 Correlation Matrix

The stochastic dependency between registered shocks is represented by a correlation matrix:

\[
R
\]

For three weather shocks:

\[
R=
\begin{bmatrix}
1 &
\rho_{Solar,Tmin} &
\rho_{Solar,Tmax}
\\
\rho_{Solar,Tmin} &
1 &
\rho_{Tmin,Tmax}
\\
\rho_{Solar,Tmax} &
\rho_{Tmin,Tmax} &
1
\end{bmatrix}
\]

The correlation matrix may include shocks belonging to different models.

For example, a future simulation could contain:

```text
SolarExposure
TemperatureMaximum
Rainfall
InflationRate
ShortRate
ElectricityPrice
```

within the same stochastic dependency structure.

The simulation engine shall therefore own the correlation/shock infrastructure rather than individual models.

For V1, the primary correlated shocks will be the weather variables.

---

## 6b.6 Correlation Matrix Validation

Before simulation begins, validate that each correlation matrix:

- is square;
- has the expected number of rows and columns;
- is symmetric within an appropriate floating-point tolerance;
- has diagonal elements equal to 1 within tolerance;
- has all correlation coefficients in the range [-1,1];
- is mathematically valid for the configured decomposition;
- can successfully be decomposed by the selected Cholesky implementation.

Invalid matrices shall cause simulation initialisation to fail.

Do not silently repair, normalise or otherwise alter an invalid user-supplied correlation matrix.

---

## 6b.7 Cholesky Decomposition

During initialisation, calculate the Cholesky factor:

\[
R=LL^T
\]

where \(L\) is lower triangular.

This calculation shall occur once for each distinct correlation matrix, not once per scenario or timestep.

For every scenario/timestep, calculate the correlated shock vector:

\[
dZ=LZ
\]

The resulting vector has the required correlation structure.

For example:

\[
\begin{bmatrix}
dZ_{Solar}\\
dZ_{Tmin}\\
dZ_{Tmax}
\end{bmatrix}
=
L
\begin{bmatrix}
Z_1\\
Z_2\\
Z_3
\end{bmatrix}
\]

The model consumes the correlated `dZ` values, not the original independent `Z` values.

---

## 6b.8 Correlation Versus Volatility

The shock generator produces standard-normal correlated shocks.

It should not apply the model's volatility or standard deviation.

For example, the weather model receives:

\[
dZ_{Solar}
\]

and performs:

\[
SolarExposure
=
\mu_{Solar,m}
+
\sigma_{Solar,m}dZ_{Solar}
\]

Likewise a future stochastic differential equation may perform:

\[
X_{t+1}
=
f(X_t,\ldots)
+
\sigma\sqrt{\Delta t}\,dZ
\]

Therefore:

```text
Shock Generator
    determines stochastic dependency

Model
    determines how the shock affects the model variable
```

This separation is important.

The shock generator should know nothing about:

```text
MJ/m2/day
degrees Celsius
interest rates
inflation
PV degradation
```

It only generates dimensionless correlated standard-normal shocks.

---

## 6b.9 DZ Cache

The correlated shocks shall be stored in a `DZCache` for use by models during the timestep.

Conceptually:

```cpp
class DZCache
{
public:
    double GetDZ(ShockIndex index) const;
};
```

A model therefore performs something conceptually equivalent to:

```cpp
double dzSolar =
    context.DZ->GetDZ(solarShockIndex);
```

The model shall resolve `solarShockIndex` during initialisation.

No string lookup shall occur during scenario execution.

---

## 6b.10 Cache Lifetime

The DZ cache does not need to retain the complete stochastic history unless a later requirement demonstrates a need for it.

The simulation value matrix already retains model outputs across all timesteps.

For V1, the DZ cache may therefore be scoped to the current scenario/timestep:

```text
Generate shocks for (s,t)
        |
        v
Store in DZ cache
        |
        v
Run all models for (s,t)
        |
        v
Reuse cache storage for (s,t+1)
```

This keeps shock storage small.

If detailed shock-path output is later required for debugging or validation, a diagnostic mode may optionally retain or write shocks.

This should not be required for normal execution.

---

## 6b.11 Worker-Local DZ Cache

Because each worker operates on exactly one scenario at a time, each worker may own a reusable DZ cache.

For example:

```text
Worker 0
    RNG for current scenario
    DZ cache

Worker 1
    RNG for current scenario
    DZ cache

...

Worker N
    RNG for current scenario
    DZ cache
```

The cache is execution workspace, not simulation state.

Therefore it does not belong in the `[scenario][timestep][value]` matrix.

No synchronization is required between worker DZ caches.

---

## 6b.12 Timestep Execution

The worker execution sequence becomes:

```cpp
for (scenario : assignedScenarios)
{
    InitialiseScenarioRNG(scenario);

    for (t = 0; t < numTimesteps; ++t)
    {
        shockGenerator.Generate(
            rng,
            t,
            dzCache);

        for (model : orderedModels)
        {
            model->RunSimulation(
                scenario,
                t,
                values,
                dzCache);
        }
    }
}
```

Therefore all stochastic shocks for `(scenario,timestep)` exist before any model for that timestep executes.

This guarantees that RNG consumption is independent of model execution order.

---

## 6b.13 Time-Dependent Correlation Matrices

The shock architecture shall permit the correlation matrix to depend on timestep characteristics.

For V1 weather modelling, correlation matrices may vary by calendar month.

For example:

```text
January  -> R_Jan -> L_Jan
February -> R_Feb -> L_Feb
...
December -> R_Dec -> L_Dec
```

All twelve Cholesky factors should be calculated during model/simulation initialisation.

At runtime:

```text
month = timestepManager.GetMonth(t);

L = weatherCorrelationFactors[month];

dZ = L * Z;
```

Do not perform a Cholesky decomposition inside the scenario/timestep loop.

Future models may use other correlation regimes.

---

## 6b.14 Independent Shocks

A shock with no correlation to another shock has correlation coefficient zero.

An entirely independent stochastic model therefore does not require special treatment.

Conceptually its correlation block is simply:

\[
R=[1]
\]

and:

\[
dZ=Z
\]

The implementation may optimise this case by avoiding an unnecessary matrix multiplication.

Such optimisation must not change the resulting stochastic stream.

---

## 6b.15 Correlation Groups

The implementation may organise shocks into independent correlation groups.

For example:

```text
Weather group
    SolarExposure
    TemperatureMinimum
    TemperatureMaximum

Interest-rate group
    ShortRate
```

If no correlation is specified between the two groups, it is unnecessary to construct one large matrix containing zero cross-correlations.

Conceptually:

\[
R=
\begin{bmatrix}
R_{weather} & 0\\
0 & R_{rates}
\end{bmatrix}
\]

may be represented internally as two independent Cholesky blocks.

This is an implementation optimisation and must not alter deterministic RNG ordering.

V1 may use either one global matrix or correlation groups, whichever results in the simpler clean implementation.

---

## 6b.16 Model Interface

The model interface should allow stochastic models to declare their shock requirements.

Conceptually:

```cpp
class Model
{
public:
    virtual std::vector<ValueType>
        GetOutputValueTypes() const = 0;

    virtual std::vector<ValueType>
        GetInputValueTypes() const = 0;

    virtual std::vector<ShockDefinition>
        GetShocks() const
    {
        return {};
    }

    virtual void RunSimulation(
        SimulationContext& context) = 0;
};
```

A deterministic model returns no shocks.

A weather model might return three.

A future Vasicek model might return one.

During initialisation the model's shock names are resolved to integer shock indices and stored by the model.

---

## 6b.17 Example Weather Model

For:

```text
SydneyWeatherRecent
```

the model declares:

```text
SolarExposureShock
TemperatureMinimumShock
TemperatureMaximumShock
```

The engine registers:

```text
dZ[0] = SydneyWeatherRecent.SolarExposure
dZ[1] = SydneyWeatherRecent.TemperatureMinimum
dZ[2] = SydneyWeatherRecent.TemperatureMaximum
```

At timestep `t`, the shock generator produces:

\[
dZ_0,dZ_1,dZ_2
\]

The weather model then performs, for the applicable month:

\[
Solar_t
=
\mu_{Solar,m}
+
\sigma_{Solar,m}dZ_0
\]

\[
Tmin_t
=
\mu_{Tmin,m}
+
\sigma_{Tmin,m}dZ_1
\]

\[
Tmax_t
=
\mu_{Tmax,m}
+
\sigma_{Tmax,m}dZ_2
\]

and writes the results into:

```text
V[s,t,SolarExposure]
V[s,t,TemperatureMinimum]
V[s,t,TemperatureMaximum]
```

The model does not know how the three `dZ` values were generated or correlated.

---

## 6b.18 Determinism Requirements

Shock generation is part of the simulation reproducibility contract.

For a given:

```text
simulator version
scenario number
timestep
shock registry
correlation configuration
```

the generated `dZ` values must be deterministic.

The following must not alter them:

```text
number of worker threads
worker scheduling
scenario block boundaries
model execution order
output configuration
```

Adding an output must never alter simulation shocks.

---

## 6b.19 Testing

Implement unit tests covering:

### RNG seeding

For known scenario numbers, verify known Mersenne Twister output sequences.

### Uniform-to-normal conversion

For known uniform values, verify expected standard-normal values.

### Independent shocks

Generate a large sample and verify:

\[
E[Z]\approx0
\]

\[
Var(Z)\approx1
\]

and cross-correlations are approximately zero.

### Cholesky transformation

For a known correlation matrix and known independent vector \(Z\), verify the exact expected transformed vector.

### Statistical correlation

Generate a large number of shocks and verify that the sample correlation matrix approximates the configured matrix.

### Time-dependent correlation

Verify that the correct monthly Cholesky matrix is selected for each timestep.

### Thread invariance

Run identical simulations using different thread counts and compare all generated model values.

### Scenario invariance

Verify that a selected scenario produces identical shocks regardless of the worker that executes it.

### Model-order invariance of shocks

Change the model execution order while preserving valid dependencies and verify that the generated shock vectors remain identical.

---

## 6b.20 Design Invariant

The key architectural rule is:

> Models consume stochastic shocks; models do not own random-number generation.

The stochastic infrastructure owns:

```text
scenario seeding
random number generation
uniform-to-normal transformation
correlation
Cholesky transformation
DZ caching
```

Models own:

```text
the interpretation of dZ
volatility
drift
state evolution
physical/economic equations
```

This permits weather, degradation, interest-rate, inflation, electricity-price and other future stochastic models to share one deterministic and internally consistent stochastic framework.

# 7. Base Model Architecture

## 7.1 Model

All simulation models shall derive from a common abstract base class.

Conceptually:

```cpp
class Model
{
public:
    virtual ~Model() = default;

    virtual void Initialise(const SimulationDefinition& simulation) = 0;

    virtual std::vector<ValueType> GetValueTypes() const = 0;

    virtual void RunSimulation(SimulationContext& context) = 0;

    virtual std::string Name() const = 0;
};
```

The exact C++ signatures may be refined during implementation.

The important requirements are:

1. Every model declares its simulation values.
2. Every model can be initialised before scenario execution.
3. Every model can execute for a specified scenario/timestep.
4. Models access simulation values through the common simulation matrix.

---

# 8. Model Inputs and Outputs

Prefer extending the base model contract to distinguish values consumed from values produced:

```cpp
virtual std::vector<ValueType> GetInputValueTypes() const;
virtual std::vector<ValueType> GetOutputValueTypes() const;
```

`GetValueTypes()` may then represent the union or may be omitted if input/output declarations make it redundant.

This information should allow the engine to validate dependencies before execution.

Example:

```text
WeatherModel outputs:
    SolarExposure
    TemperatureMaximum
    TemperatureMinimum

PVArray model consumes:
    SolarExposure
    TemperatureMaximum
    TemperatureMinimum
    DegradationFactor

PVArray produces:
    PVGenerationKWh
```

Missing required values should result in configuration failure rather than a runtime failure during scenario execution.

---

# 9. Model Dependency Ordering

Models within a timestep may depend upon values generated by other models in the same timestep.

For example:

```text
Weather
   |
   v
PV Degradation
   |
   v
PV Array
   |
   v
Installation
```

The simulation must establish a deterministic execution order before scenario execution begins.

Preferably build a dependency graph from model input/output declarations and perform a topological sort.

The engine shall reject:

- missing producers;
- ambiguous invalid dependencies;
- cyclic same-timestep dependencies.

Do not implement iterative cyclic dependency resolution in V1.

Historical dependencies such as:

```text
V[s,t-1,v]
```

do not constitute same-timestep dependency cycles.

---

# 10. Historical Values

Models are explicitly permitted to access previous simulation values.

Examples:

```cpp
GetValue(s, t - 1, ValueType::DegradationFactor);
```

and potentially:

```cpp
GetValue(s, t - n, someValue);
```

The entire simulation history is deliberately retained.

Do not implement rolling buffers or output-dependent retention optimisation in V1.

This allows future Markov and path-dependent models to be implemented without changing the storage architecture.

---

# 11. Model Classes Required for V1

At minimum implement the following conceptual model types.

## 11.1 WeatherModel

Abstract base:

```cpp
class WeatherModel : public Model
{
};
```

Initial implementation:

```text
CorrelatedMonthlyWeatherModel
```

Outputs:

```text
SolarExposure
TemperatureMinimum
TemperatureMaximum
```

The model should support month-specific means and standard deviations.

It should generate correlated stochastic shocks using a supplied monthly correlation matrix and Cholesky decomposition.

Conceptually:

\[
z_c = Lz
\]

where:

```text
z = independent standard normal shocks
L = Cholesky factor
z_c = correlated shocks
```

Then:

\[
X=\mu+\sigma z_c
\]

for each weather variable.

The model implementation should be replaceable later by:

```text
EmpiricalWeatherModel
AutoregressiveWeatherModel
RegimeSwitchingWeatherModel
PeriodicWeatherModel
```

without modifying the engine.

---

# 12. Weather Model Provenance

Weather configuration should preserve:

```text
location
latitude
longitude
training period
source provider
source station IDs
```

For the initial Sydney model:

```text
Solar:
BOM station 066006
Sydney Botanic Gardens

Temperature:
BOM station 066037
Sydney Airport AMO
```

The engine itself should not contain BOM-specific behaviour.

BOM processing is an input-data/model-calibration concern.

---

# 13. PVDegradationModel

Define an abstract degradation model:

```cpp
class PVDegradationModel : public Model
{
};
```

V1 implementation:

```text
CompoundAnnualPVDegradationModel
```

Conceptually:

\[
D(t)=(1-d)^{t}
\]

with appropriate adjustment for timestep size.

Output:

```text
DegradationFactor
```

Installed/nameplate capacity must remain constant.

Degradation modifies effective output, not `capacity_watts`.

Future implementations may include:

```text
FirstYearThenAnnualDegradation
EmpiricalDegradationCurve
StochasticDegradation
MarkovDegradation
```

Therefore degradation behaviour must not be embedded directly in the PV array or installation class.

---

# 14. Panel Model

Define a panel technology/model class.

Example configuration:

```text
LGPanel
```

Properties may include:

```text
rated efficiency
temperature coefficient
reference temperature
degradation model reference
```

Panel technology represents the physical panel characteristics.

Do not combine panel technology with installation geometry.

---

# 15. PV System Model

Define a model representing system-level losses.

V1 may use a simple performance ratio:

```text
StandardPVSystem
    performance_ratio = 0.85
```

Future implementations may split this into:

```text
inverter losses
wiring losses
mismatch losses
soiling
curtailment
```

Do not hard-code the performance ratio into the PV array calculation.

---

# 16. PVArray

A PV installation contains one or more arrays.

Suggested class:

```cpp
class PVArray
{
public:
    std::string Name;

    double CapacityWatts;
    double AzimuthDegrees;
    double TiltDegrees;

    PanelModel* Panel;
    PVSystemModel* System;
};
```

An array represents a physical group of panels sharing geometry and technology.

Azimuth and tilt must be separate values.

Use explicit property names:

```text
azimuth_degrees
tilt_degrees
```

Document one azimuth convention and use it consistently.

Recommended:

```text
0 degrees    = North
+90 degrees  = East
-90 degrees  = West
180 degrees  = South
```

---

# 17. Installation

Define an installation entity.

Suggested conceptual structure:

```cpp
class Installation
{
public:
    std::string Name;

    WeatherModel* Weather;

    std::vector<PVArray> Arrays;
};
```

An installation may contain multiple PV arrays.

Example:

```text
SydneyHouse
    NorthRoof
        6000 W
        azimuth 0
        tilt 32.5

    WestRoof
        4000 W
        azimuth -90
        tilt 25
```

Total installation generation is the sum of its arrays.

Installations sharing a weather model must use the **same weather scenario path**.

Do not generate independent weather shocks for each installation.

This is essential for paired Monte Carlo comparisons.

---

# 18. Physical Entities Versus Processes

Maintain the distinction:

```text
Installation / PVArray / Panel
    = physical configuration/entity

WeatherModel / DegradationModel
    = processes acting on entities
```

Do not turn every entity into a stochastic model.

Future examples:

```text
Battery
    entity/state

BatteryDegradationModel
    stochastic/path-dependent process
```

---

# 19. Random Number Generation

## 19.1 Generator

Use Mersenne Twister.

The precise implementation should be isolated behind a small RNG abstraction so it can later be replaced if necessary.

Models should obtain random values from the scenario RNG supplied through `SimulationContext`.

---

# 20. Scenario-Based RNG Seeding

Randomness is associated with **scenario number**, not thread number.

For each scenario:

```text
Seed MT with scenario number
Generate one MT value
Reseed MT using that value
Run scenario
```

Conceptually:

```cpp
rng.Seed(scenario);
auto seed = rng.NextUInt();
rng.Seed(seed);
```

All random draws for that scenario then come from that RNG stream.

The purpose of the second seed is to scramble sequential scenario numbers before using the actual simulation stream.

The exact seeding algorithm becomes part of the simulation reproducibility contract and should be covered by tests.

There shall be no simulation-level `random_seed` input in V1.

---

# 21. Determinism Requirement

Given:

- identical input configuration;
- identical simulator version;
- identical scenario number;

the stochastic scenario must be reproducible.

Changing:

```text
thread count
thread scheduling
scenario block assignment
```

must not change scenario results.

For example:

```text
Scenario 786 with threads=1
```

must produce exactly the same simulated path as:

```text
Scenario 786 with threads=16
```

subject only to explicitly documented floating-point/platform limitations.

Ideally tests should require bit-identical results on the same platform/build.

---

# 22. Threading Model

Scenarios are independent.

Partition the scenario range into contiguous blocks.

Example for 2,000 scenarios and four threads:

```text
Thread 0: scenarios    0-499
Thread 1: scenarios  500-999
Thread 2: scenarios 1000-1499
Thread 3: scenarios 1500-1999
```

Each worker executes:

```cpp
for (scenario : assignedScenarios)
{
    InitialiseScenarioRng(scenario);

    for (timestep = 0; timestep < numTimesteps; ++timestep)
    {
        for (model : orderedModels)
        {
            model->RunSimulation(context);
        }
    }
}
```

No worker processes another worker's scenarios.

Therefore normal simulation matrix access requires:

```text
no locks
no atomics
no mutexes
no concurrent collections
```

There are no read/write conflicts between workers because scenarios are independent.

Synchronization is required only around execution lifecycle operations such as:

```text
allocate
launch workers
join workers
produce outputs
```

---

# 23. False Sharing / Cache Behaviour

Scenario blocks should be contiguous.

Because each scenario occupies:

```text
T * V * sizeof(double)
```

bytes, adjacent workers will normally be separated by much more than a cache line.

Do not add padding or elaborate cache-management logic unless profiling demonstrates a need.

Correctness and deterministic behaviour take precedence over speculative cache optimisation.

---

# 24. Execution Order

The preferred hot-path ordering is:

```text
for each scenario
    for each timestep
        for each dependency-ordered model
            execute model
```

This has two advantages:

1. It naturally supports Markov/path-dependent models.
2. Values for the current timestep remain relatively cache-local while dependent models consume them.

Do not restructure execution model-by-model across the entire simulation unless profiling later demonstrates a compelling reason.

---

# 25. Timestep Management

Implement a `TimestepManager`.

It must provide at least:

```cpp
double GetDt(size_t timestep);
double GetElapsedYears(size_t timestep);
```

Input shall support timestep ranges.

Example:

```json
"timesteps": 120,
"timestep_sizes": [
    {
        "start_timestep": 1,
        "end_timestep": 120,
        "timestep_size": "1M"
    }
]
```

V1 will primarily use monthly timesteps.

Do not assume all future simulations use monthly timesteps.

Future versions may use:

```text
30 minutes
1 hour
1 day
1 month
mixed timestep ranges
```

---

# 26. Input Configuration

Use JSON.

Top-level conceptual structure:

```json
{
    "simulation": {
        "settings": {},
        "models": [],
        "installations": [],
        "outputs": []
    }
}
```

---

# 27. Simulation Settings

Example:

```json
{
    "scenarios": 2000,
    "threads": 8,
    "timesteps": 120,
    "timestep_sizes": [
        {
            "start_timestep": 1,
            "end_timestep": 120,
            "timestep_size": "1M"
        }
    ]
}
```

Required validation includes:

```text
scenarios > 0
threads > 0
timesteps > 0
threads <= sensible implementation limit
timestep ranges cover required timesteps
timestep ranges do not overlap incorrectly
```

Do not silently repair invalid input.

Fail with useful error messages.

---

# 28. Model Configuration

Models are named objects.

Example:

```json
{
    "name": "SydneyWeatherRecent",
    "type": "CorrelatedMonthlyWeather",
    "...": "model-specific parameters"
}
```

References elsewhere in the configuration use the model's name.

Model names must be unique.

Use a factory/registry mechanism:

```text
type string
    ->
model factory
    ->
Model instance
```

Avoid a giant parser switch statement if a simple registration mechanism can provide extensibility.

---

# 29. Weather Configuration

A weather model should conceptually support configuration similar to:

```json
{
    "name": "SydneyWeatherRecent",
    "type": "CorrelatedMonthlyWeather",

    "location": {
        "name": "Sydney",
        "latitude": -33.87,
        "longitude": 151.22
    },

    "training_period": {
        "start": "2016-01-01",
        "end": "2025-12-31"
    },

    "source": {
        "provider": "BOM",
        "solar_station": "066006",
        "temperature_station": "066037"
    },

    "solar_exposure": {
        "units": "MJ/m2/day",
        "distribution": "normal",
        "monthly": []
    },

    "temperature_minimum": {
        "units": "C",
        "distribution": "normal",
        "monthly": []
    },

    "temperature_maximum": {
        "units": "C",
        "distribution": "normal",
        "monthly": []
    },

    "dependence_model": {
        "type": "correlation_matrix",
        "variables": [
            "solar_exposure",
            "temperature_minimum",
            "temperature_maximum"
        ],
        "monthly": []
    }
}
```

The actual monthly statistics will be populated by the weather data processor.

Correlation matrices must be validated.

At minimum validate:

```text
square
correct dimension
symmetric
diagonal approximately 1
entries between -1 and +1
positive semidefinite
compatible with Cholesky implementation
```

If standard Cholesky requires positive definiteness, fail clearly when the supplied matrix cannot be decomposed.

Do not silently alter a supplied correlation matrix.

---

# 30. Input Parser

Implement a dedicated configuration/input layer.

Responsibilities:

1. Parse JSON.
2. Validate syntax.
3. Validate required fields.
4. Convert textual enums/value names to internal enums.
5. Instantiate model objects.
6. Resolve named references.
7. Validate model parameters.
8. Collect required `ValueType`s.
9. Validate model dependencies.
10. Establish deterministic model execution order.
11. Construct installations and arrays.
12. Construct output requests.
13. Construct timestep definitions.
14. Return a fully resolved `SimulationDefinition`.

The parser should finish all expensive string/name resolution before simulation execution begins.

The simulation kernel should receive resolved objects, enum IDs and indices rather than repeatedly interpreting JSON.

---

# 31. Configuration Errors

Configuration failures should identify:

```text
JSON path or object name
invalid value
expected constraint
```

Example:

```text
Installation 'SydneyHouse':
array 'WestRoof':
unknown panel model 'LGPanel2'
```

or:

```text
Output 3:
unknown value 'banana'
```

Do not allow malformed configuration to fail later as an obscure simulation exception.

---

# 32. Output Architecture

Outputs are **queries against the completed simulation matrix**.

Outputs must not determine what values are retained during simulation.

The entire simulation matrix exists independently of output requests.

Define an abstract output/request class.

Conceptually:

```cpp
class Output
{
public:
    virtual ~Output() = default;

    virtual void Write(
        const Simulation& simulation,
        const SimulationValueMatrix& values) = 0;
};
```

Potential concrete V1 class:

```text
CsvOutput
```

The parser may construct a higher-level `OutputRequest`, with a writer responsible only for serialisation.

---

# 33. Output Value Selection

Outputs shall use an array of values even when only one is requested.

Use:

```json
"values": [
    "solar_exposure"
]
```

not:

```json
"value": "solar_exposure"
```

This keeps the schema consistent.

---

# 34. Scenario Output

Support exact scenario-path extraction.

Example:

```json
{
    "type": "model",
    "name": "SydneyWeatherRecent",

    "values": [
        "solar_exposure",
        "temperature_minimum",
        "temperature_maximum"
    ],

    "aggregation": "scenario",

    "scenarios": [
        1,
        786,
        12345
    ],

    "timestep_start": 1,
    "timestep_end": 120,

    "output_format": "csv"
}
```

`aggregation = scenario` means:

- do not aggregate across scenarios;
- emit the requested scenario paths exactly.

Scenario IDs in an output request must exist within the configured simulation range.

---

# 35. Statistical Outputs

The architecture should support outputs such as:

```json
{
    "type": "installation",
    "name": "SydneyHouse",

    "values": [
        "pv_generation_kwh",
        "degradation_factor"
    ],

    "aggregation": "annual",

    "statistics": [
        "mean",
        "std_dev",
        "p05",
        "p50",
        "p95"
    ],

    "timestep_start": 1,
    "timestep_end": 120,

    "output_format": "csv"
}
```

For V1 implement only the statistics required for the initial test cases, but structure the output subsystem so additional statistics are straightforward to add.

Keep the concepts separate:

```text
aggregation
```

means temporal/scenario grouping, while:

```text
statistic
```

means the mathematical statistic calculated over the resulting sample.

---

# 36. CSV Writer

Implement CSV output initially.

The CSV writer must:

- use deterministic column ordering;
- include meaningful headers;
- preserve scenario and timestep identifiers where applicable;
- use locale-independent numeric formatting;
- use sufficient double precision for reproducibility/testing;
- fail clearly if the destination cannot be written.

Do not make CSV generation part of worker execution.

Generate outputs after all scenario workers have joined.

---

# 37. PV Calculation

V1 should implement a deliberately simple PV calculation.

Conceptually:

\[
Generation =
SolarResource
\times InstalledCapacity
\times GeometryFactor
\times TemperatureFactor
\times DegradationFactor
\times SystemPerformanceFactor
\]

The exact V1 equations should be isolated behind model classes.

Do not embed PV equations in the simulation engine.

The purpose of V1 is to establish architecture and deterministic execution, not to produce a final high-fidelity PV physics model.

---

# 38. Shared Weather Paths

This is a critical invariant.

If multiple installations reference:

```text
SydneyWeatherRecent
```

then within scenario `s` and timestep `t` they must observe exactly the same:

```text
SolarExposure
TemperatureMinimum
TemperatureMaximum
```

Do not instantiate independent stochastic weather paths per installation.

This provides common random numbers and permits low-noise paired comparisons between installation alternatives.

---

# 39. Simulation Lifecycle

The overall lifecycle should be approximately:

```text
Read JSON
    |
    v
Parse configuration
    |
    v
Instantiate models/entities
    |
    v
Resolve references
    |
    v
Collect ValueTypes
    |
    v
Build dense ValueType mapping
    |
    v
Validate dependencies
    |
    v
Topologically order models
    |
    v
Initialise timestep manager
    |
    v
Initialise models
    |
    v
Allocate V[S,T,V]
    |
    v
Partition scenarios
    |
    v
Launch workers
    |
    v
Run scenarios
    |
    v
Join workers
    |
    v
Process output queries
    |
    v
Write CSV
```

---

# 40. Initialisation Versus Scenario Execution

Keep these phases clearly separated.

## Initialisation

May perform:

```text
JSON parsing
string lookup
model factory lookup
reference resolution
parameter validation
ValueType registration
dependency analysis
topological sorting
Cholesky decomposition
precomputation of timestep dt values
precomputation of model constants
memory allocation
```

## Scenario execution

Should predominantly perform:

```text
array indexing
floating-point arithmetic
RNG generation
model state transitions
matrix reads/writes
```

Avoid configuration parsing, map lookup and string manipulation in the scenario hot path.

---

# 41. Exceptions

Exceptions may be used for:

```text
invalid configuration
initialisation failure
invalid model parameters
missing ValueTypes
invalid dependency graph
output failure
```

Normal scenario execution should not use exceptions for control flow.

---

# 42. V2 Architectural Requirements

The following are **not required implementations in V1**, but V1 must not prevent them.

## 42.1 Inflation model

Future:

```text
MeanRevertingInflationModel
```

likely based on an Ornstein-Uhlenbeck process.

Potential values:

```text
InflationRate
InflationIndex
```

---

## 42.2 Interest rate model

Future:

```text
OneFactorVasicek
```

The existing implementation can be used as a reference.

The old implementation already delegates its stochastic rate process to `OrnsteinUhlenbeck`, supports `LOGRATE`, `CASHRATE` and `CASHROLLUP`, and calculates Vasicek zero-coupon prices. The new engine should eventually port the mathematical model rather than the old thread-oriented storage architecture.

---

## 42.3 Economic model

Future economic models should consume physical simulation values:

```text
PVGenerationKWh
GridImportKWh
GridExportKWh
```

and produce:

```text
InstallationCost
ElectricityValue
ExportRevenue
MaintenanceCost
NetCashflow
```

Economic models are ordinary simulation models.

The engine must not distinguish between a physical double and a financial double.

Both are simply `ValueType`s stored in:

\[
V[s,t,v]
\]

---

# 43. Inflation-Adjusted Values

Future economic models should be able to maintain an inflation index:

\[
I_0=1
\]

and evolve it from simulated inflation.

Nominal cashflows may then be converted to today's purchasing-power terms.

Keep this concept separate from interest-rate discounting.

The engine itself should impose no special semantics on either operation.

---

# 44. IRR / NPV

IRR is a future **output calculation**, not a simulation model.

The simulation will produce scenario cashflows:

\[
CF_{s,t}
\]

The output system can then calculate:

```text
IRR per scenario
NPV per scenario
mean IRR
median IRR
IRR percentiles
probability IRR exceeds threshold
```

This is another reason the complete scenario path must remain available after execution.

The output/statistics architecture should therefore allow future statistics that consume an entire time series rather than a single `[s,t,v]` value.

---

# 45. Future Stochastic Processes

The architecture must permit models such as:

```text
OrnsteinUhlenbeck
Vasicek
Markov degradation
weather regime switching
periodic weather
component failures
battery degradation
electricity price processes
load processes
```

without changes to the simulation matrix or threading architecture.

A stateful model simply reads previous values from:

```text
V[s,t-1,v]
```

and writes its new state to:

```text
V[s,t,v]
```

---

# 46. Future Weather Periodicity

Do not assume weather observations are independent between timesteps.

Future weather models may incorporate:

```text
serial correlation
multi-year periodicity
rainfall
wet/dry regimes
ENSO-type latent states
reservoir-related models
```

These belong inside weather/process model implementations.

The engine should remain unaware of their mathematics.

---

# 47. Testing Requirements

Testing is a first-class V1 requirement.

## 47.1 Matrix tests

Test:

```text
SetValue/GetValue
scenario boundaries
timestep boundaries
ValueType mapping
different S/T/V dimensions
invalid ValueType access
```

---

## 47.2 RNG reproducibility

For selected scenario IDs record known RNG sequences.

Tests should confirm that the double-seeding algorithm always generates the expected stream.

Example scenarios:

```text
0
1
2
786
12345
1999
```

---

## 47.3 Thread invariance

This is a critical test.

Run identical input with:

```text
threads = 1
threads = 2
threads = 4
threads = 8
```

Compare the complete simulation matrices.

They must be identical.

---

## 47.4 Scenario invariance

Scenario `s` must produce the same result regardless of which worker processes it.

---

## 47.5 Dependency ordering

Create trivial test models:

```text
A produces X
B consumes X and produces Y
C consumes Y and produces Z
```

Supply them in deliberately incorrect configuration order.

Verify the engine executes:

```text
A -> B -> C
```

Also test:

```text
missing dependency
cycle
duplicate producer where prohibited
```

---

## 47.6 Historical dependency

Create a simple model:

\[
X_t=X_{t-1}+1
\]

and verify state propagation across timesteps.

---

## 47.7 Weather correlation

Generate a sufficiently large test simulation and verify generated sample correlations approximately reproduce configured correlations.

Also separately unit-test the Cholesky transform with deterministic input vectors.

---

## 47.8 Installation aggregation

Create two arrays with known deterministic outputs and verify:

\[
InstallationGeneration =
Array1Generation + Array2Generation
\]

---

## 47.9 Output tests

Verify:

```text
scenario selection
timestep selection
multiple values
mean
standard deviation
percentiles
annual aggregation
CSV headers
CSV deterministic ordering
```

---

# 48. Performance Testing

Add a simple benchmark configuration:

```text
2,000 scenarios
120 monthly timesteps
representative V1 model set
8 threads
```

Measure separately:

```text
configuration parsing
initialisation
matrix allocation
simulation execution
output calculation
CSV writing
```

Do not optimise based on assumptions.

Profile first.

The expected simulation workload is small enough that architectural clarity and deterministic behaviour are substantially more important than micro-optimisation.

---

# 49. Logging

Logging should primarily cover lifecycle and diagnostics:

```text
configuration loaded
models instantiated
ValueTypes registered
matrix dimensions
matrix allocated bytes
dependency execution order
scenario count
thread count
worker scenario ranges
simulation elapsed time
output processing elapsed time
```

Do not log per-timestep/per-scenario information during normal operation.

Provide optional debug logging where useful.

---

# 50. Suggested Class Structure

Conceptually:

```text
Simulation
|
+-- SimulationSettings
|
+-- TimestepManager
|
+-- ValueTypeRegistry
|
+-- SimulationValueMatrix
|
+-- ModelRegistry / ModelFactory
|
+-- Models
|   |
|   +-- Model                         [abstract]
|       |
|       +-- WeatherModel              [abstract]
|       |   |
|       |   +-- CorrelatedMonthlyWeatherModel
|       |
|       +-- PVDegradationModel        [abstract]
|       |   |
|       |   +-- CompoundAnnualPVDegradationModel
|       |
|       +-- PanelModel
|       |
|       +-- PVSystemModel
|
+-- Installations
|   |
|   +-- Installation
|       |
|       +-- PVArray[]
|
+-- Execution
|   |
|   +-- ScenarioRunner
|   +-- ScenarioPartitioner
|   +-- RandomGenerator
|
+-- Output
|   |
|   +-- OutputRequest
|   +-- OutputProcessor
|   +-- OutputWriter                  [abstract]
|       |
|       +-- CsvOutputWriter
|
+-- Configuration
    |
    +-- InputParser
    +-- ConfigurationValidator
```

The exact source-file layout is left to implementation, provided responsibilities remain cleanly separated.

---

# 51. Important Design Rules

The implementation must preserve the following invariants.

### Rule 1

The simulation engine knows about:

```text
scenario
time
values
models
```

It does not know what "solar" means.

### Rule 2

Thread ID never determines simulation results.

### Rule 3

Scenario number determines the stochastic RNG stream.

### Rule 4

All values required by the configured simulation are registered before matrix allocation.

### Rule 5

Strings are resolved before scenario execution.

### Rule 6

The simulation matrix is fully allocated and retained for the entire run.

### Rule 7

Models may freely access historical values for their own scenario.

### Rule 8

Different scenarios never read or write each other's state during simulation.

### Rule 9

Model execution order is deterministic and respects same-timestep dependencies.

### Rule 10

Installations referencing the same stochastic model share the same scenario path.

### Rule 11

Output configuration does not influence simulation retention or execution.

### Rule 12

Physical models, stochastic processes, economic models and output statistics remain separate concepts.

---

# 52. Explicit Non-Goals for V1

Do not implement unless required to complete the V1 architecture:

```text
battery storage
battery optimisation
household load
electricity tariffs
electricity forward contracts
inflation
interest rates
cashflow modelling
IRR
NPV
component failure
rainfall
weather periodicity
weather regime switching
hourly weather
30-minute simulation
GPU execution
distributed execution
dynamic matrix resizing
sparse matrix storage
streaming scenario output
database persistence
GUI
web API
```

However, do not make architectural choices that make these unnecessarily difficult to add.

---

# 53. Recommended Implementation Sequence

Implement in this order:

1. `ValueType` and `ValueTypeRegistry`.
2. `SimulationValueMatrix`.
3. `TimestepManager`.
4. RNG abstraction and deterministic scenario seeding.
5. `SimulationContext`.
6. abstract `Model`.
7. trivial deterministic test models.
8. dependency graph/model ordering.
9. `ScenarioRunner`.
10. multithreaded scenario partitioning.
11. determinism/thread-invariance tests.
12. JSON configuration structures.
13. input parser and validation.
14. model factory.
15. weather model.
16. PV degradation model.
17. panel/system models.
18. `PVArray`.
19. `Installation`.
20. PV generation.
21. output request architecture.
22. CSV writer.
23. statistics/aggregation.
24. complete integration tests.
25. benchmark/profile.

Do not begin by implementing detailed PV physics.

First prove the generic simulation kernel.

---

# 54. V1 Acceptance Criteria

V1 is complete when the following demonstration succeeds.

Given a JSON configuration containing:

```text
2,000 scenarios
configurable thread count
120 monthly timesteps
Sydney stochastic weather model
PV degradation model
panel model
PV system model
installation containing multiple PV arrays
scenario outputs
statistical outputs
```

the executable shall:

1. Parse and validate the configuration.
2. Instantiate and resolve all models.
3. Build the required `ValueType` mapping.
4. Allocate one contiguous simulation matrix.
5. Establish model dependency order.
6. Partition scenarios across the requested workers.
7. Generate a deterministic RNG stream from each scenario number.
8. Run every scenario independently.
9. Produce identical scenario values regardless of worker count.
10. Retain the complete `[scenario][timestep][value]` cube.
11. Extract requested scenario paths.
12. Calculate requested aggregate statistics.
13. Write deterministic CSV output.
14. Reject malformed or internally inconsistent configurations with useful diagnostic messages.

The most important architectural test is:

> Running the same configuration with a different number of threads must not change a single simulated scenario value.

If that invariant holds, and new `Model` implementations can be added without modifying the simulation kernel, the V1 engine architecture has achieved its primary objective.