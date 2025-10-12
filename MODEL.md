# Model

Notes on model elements in P7 diagrams.

- All P7 packages need to be stereotype `DataModel`
- All P7 objects need to be stereotyped with `DataElement`
- All P7 objects need to be stereotype with one of: `idlUnion`, `idlEnum`, `idlStruct`, `idlTypedef`

## Napespaces

- We can have nampespaces/packages
- those can be nested
- package with classes cannot have other packages (so only packages without classes can have subpackages)

## Naming

All modelled elements must be named with alpha-numeric characters and underscores.
Naming conventions follow Python ones (https://peps.python.org/pep-0008/):

- PascalCase for classees - `FirstClass`
- snake_case for packages - `first_package`
- snake_case for variables/attributes - `first_value`
- Enum types suffixed with Enum - `FooEnum_FIRST_VALUE`

## Type definitions

- use `idlTypedef` (IDL) and `DataElement` (NAF) stereotypes
- have no fields
- have a primitive type as parent

  - `string`
  - `float`
  - `double`
  - `integer`
  - `bool`

- can have various tags
- one of the tags can be `unit` - with short string, prefer [SI](https://www.bipm.org/en/measurement-units), this is just informative:

  - "m" - meters
  - "s" - seconds
  - "Hz" - hertz
  - "%" - percent

## Enumerations

- use `idlEnum` (IDL) and `DataElement` (NAF) stereotypes
- its name is always suffixed by `Enum`, like `MeasurementTypeEnum`
- all its members are prefixed by names, `MeasurementTypeEnum_TEMPERATURE` (because in some languages enums are global)

## Structures

- use `idlStruct` (IDL) and `DataElement` (NAF) stereotypes
- use generalization for inheritance

### Fields

- fields have a name and type (that should match actual type)
- should be public (this is interface what we design, not class)
- fields can have multiplicity [from..to]

  - [0..*] - means not limited sequence/list
  - [0..5] - means sequence/list of maximum 5 elements
  - [1..5] - means sequence/list of minimum 1 element and maximum 5 elements
  - [1..*] - means sequence/list of minimum 1 element and no upper bound

- fields can have `<<optional>>` stereotype

  - not all `<<optiona>>` and multiplicity make sense, not in all languages
  - all sequences with no lower bound ([0..*] & [0..5]) de-facto optional (but no list is different than empty list)

- all list/sequence need to have `is_collection` flag set to `True`

- actual type is discovered via association

  - from structure to field
  - direction is from source to destination
  - with TARGET set to name of field

![Sequences and optionals](./docs/images/sequences_optional.png)

```c
struct Store {
    core::data::types::Identifier one;
    sequence<core::data::types::Identifier> sequence;
    @optional
    core::data::types::Identifier optional_one;
    @ext::maxItems(5)
    sequence<core::data::types::Identifier, 5> sequence_upper_bound;
    @ext::minItems(1)
    sequence<core::data::types::Identifier> sequence_lower_bound;
    @ext::minItems(1)
    @ext::maxItems(5)
    sequence<core::data::types::Identifier, 5> sequence_bound;
    @optional
    sequence<core::data::types::Identifier> optional_sequence;
    @ext::maxItems(5)
    @optional
    sequence<core::data::types::Identifier, 5> optional_sequence_upper_bound;
};
```

## Unions

Union is a class that has multiple exclusive fields.

- use `idlUnion` (IDL) and `DataElement` (NAF) stereotypes
- it has association to enumeration, that assotiation has `<<union>>` stereotype

  - assuming that union name is `Measurement` the enumeration name is `MeasurementTypeEnum`
  - for each union members (fields), enumeration has an entry `MeasurementTypeEnum_FIELD_NAME_CAPITALIZED`
  - enumeration can have more entries

![Union](./docs/images/union.png)

```c
enum IdentifierOrNameTypeEnum {
    @value(3) IdentifierOrNameTypeEnum_NAME,
    @value(1) IdentifierOrNameTypeEnum_IDENTIFIER
};
union IdentifierOrName switch (core::data::IdentifierOrNameTypeEnum) {
    case core::data::IdentifierOrNameTypeEnum_IDENTIFIER:
        core::data::types::Identifier identifier;
    case core::data::IdentifierOrNameTypeEnum_NAME:
        core::data::types::Name name;
};
  ```

Unions are also special when put togethere with `filter_stereotypes` option. This union normally get generated like this:

![Union and steareotypes](./docs/images/union_stereo.png)

```c

enum MeasurementTypeEnum {
    @value(1) MeasurementTypeEnum_TEMPERATURE_MEASUREMENT,
    @value(0) MeasurementTypeEnum_STRING
};
union Measurement switch (core::data::MeasurementTypeEnum) {
    case core::data::MeasurementTypeEnum_TEMPERATURE_MEASUREMENT:
        core::data::types::TemperatureMeasurement temperature_measurement;
    case core::data::MeasurementTypeEnum_STRING:
        string string;
};

sequence<core::data::Measurement, 5> body;
```

Lets assume that `hibw` is filtered out in this case, the whole `Measurement` is gone and `TemperatureMeasurement` is used directly instead.
This is done to reduce nesting of generated outputs.

```c
sequence<core::data::types::TemperatureMeasurement, 5> body;
```



## mapping

| Model name            | IDL name         | custom | comment                                                                            |
| --------------------- | ---------------- | ------ | ---------------------------------------------------------------------------------- |
| maximum               | max              | false  | inclusive maximum                                                                  |
| exclusiveMaximum      | exclusiveMaximum | true   |                                                                                    |
| minimum               | min              | false  | inclusive minimum                                                                  |
| exclusiveMinimum      | exclusiveMinimum | true   |                                                                                    |
| pattern               | pattern          | true   |                                                                                    |
| interface             | interface        | true   | for messages/interface definitinons (top level)                                    |
| maxItems              | maxItems         | true   |                                                                                    |
| minItems              | minItems         | true   |                                                                                    |
| isFinalSpecialization | final            |        |                                                                                    |
|                       | appendable       |        |                                                                                    |
|                       | mutable          |        |                                                                                    |
| unit                  | unit             | false  | unit, prefer https://www.bipm.org/en/measurement-units as stated in IDL definition |
|                       | value            |        | taken from initial value of attribute                                              |
