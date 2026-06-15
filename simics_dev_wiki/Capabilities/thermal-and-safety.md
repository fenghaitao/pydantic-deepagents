[← Device Overview](overview.md)

---

# thermal-and-safety — dmr_imh_hwrs_fv

This page documents the Simics thermal-and-safety capability implemented by the dmr_imh_hwrs_fv device model. It describes what is modeled, how the model is implemented in DML, the observable behavior, testable assertions, integration touch-points, and developer guidance for extending or changing behavior.

Source files:
- srv-pm/code/hwrs-gen2/attributes.dml — device attribute overrides and handlers. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- common/code/platform-common/unified-common-code/signals/signal-templates.dml — signal_input template implementation used by thermtrip_in. *Source: common/code/platform-common/unified-common-code/signals/signal-templates.dml*
- dmr_imh_hwrs_fv device DML (device definition and pseudo attribute declaration). *Source: device DML: dmr_imh_hwrs_fv*

---

## Overview

- Modeled feature: a thermal-trip input line (hardware-sensed THERMTRIP#) and a firmware-controlled thermal-trip output line (THERMAL_TRIP_OUT) on the HWRS device.
- Role: The capability models detection of an externally driven thermal-trip input and propagation of a thermal-trip condition toward downstream controllers. It also exposes a firmware back-door to assert/deassert the same downstream thermal-trip line from firmware for test, recovery, or forced-failure purposes.
- Scope / fidelity:
  - Simulated: discrete boolean signal semantics for thermtrip_in (edge detection, HAP notification), inverted forwarding logic from the input to THERMAL_TRIP_OUT, firmware-controlled path via a pseudo attribute (thermal_trip) driving THERMAL_TRIP_OUT, HAP events fired on edges, and logging of duplicate-edge violations.
  - Stubbed / not modeled: no register-level side-effects or FSM state machine visible for this capability in the provided DML; no persistent checkpointing for the firmware back-door state (thermal_trip is explicitly configured as a pseudo attribute and excluded from checkpoint/restore). *Source: srv-pm/code/hwrs-gen2/attributes.dml*

---

## How It's Simulated

- Ports / interfaces used:
  - INPUT port thermtrip_in — implemented using the signal_input template. The template provides:
    - boolean level storage,
    - methods signal_raise and signal_lower,
    - enforcement of unique edge transitions (duplicate-edge attempts are logged as a specification violation),
    - HAP posting for rising-edge, falling-edge and any-edge observers. *Source: common/code/platform-common/unified-common-code/signals/signal-templates.dml*
  - OUTPUT CONNECT THERMAL_TRIP_OUT — modeled as a CONNECT node that the device drives (signal_raise/signal_lower) to represent the asserted/deasserted downstream thermal-trip line. *Source: srv-pm/code/hwrs-gen2/attributes.dml*

- DML constructs and wiring:
  - thermtrip_in uses the signal_input template in the device DML (port interface = signal_input). The device-level attributes.dml contains overrides that observe thermtrip_in changes and perform inverted forwarding into device logic that drives THERMAL_TRIP_OUT.
  - thermal_trip is declared as a pseudo attribute on the device (configuration = "pseudo"). It is intentionally excluded from checkpoint/restore and acts as a firmware back-door handle. Device attribute handlers use this attribute to set THERMAL_TRIP_OUT. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
  - Both the input-forwarding path (via attributes.dml overrides) and the pseudo attribute handler ultimately call signal_raise/signal_lower on the THERMAL_TRIP_OUT CONNECT to represent the line state to downstream components.

- Events and scheduling:
  - Edge HAP events are posted synchronously by the signal_input template when signal_raise/signal_lower are invoked. No timer- or delay-based scheduling is specified for this capability. *Source: common/code/platform-common/unified-common-code/signals/signal-templates.dml*
  - No device-internal timers, deferred actions, or scheduled FSM transitions are described in the DML fragments provided.

- Fault/consistency checks:
  - The signal_input template enforces unique edge transitions (if the same edge is asserted twice, the template logs a specification-violation). *Source: common/code/platform-common/unified-common-code/signals/signal-templates.dml*
  - There are no additional guards or arbitration logic visible in the DML snippet; resolution when firmware and external input both attempt to control THERMAL_TRIP_OUT is determined by the device overrides in attributes.dml (see Implementation Notes). *Source: srv-pm/code/hwrs-gen2/attributes.dml*

---

## Working Flow

Two primary flows are implemented:

1) FLOW: external-thermtrip-input
- Trigger: an upstream component invokes thermtrip_in.signal_raise() (external THERMTRIP# asserted).
- Steps:
  1. signal_input template records the asserted boolean level, enforces transition uniqueness, and posts a rising-edge HAP to registered observers.
  2. Device-specific override code implemented in attributes.dml observes the template change and performs inverted forwarding into the device logic.
  3. The forwarding code drives the THERMAL_TRIP_OUT CONNECT to the inverted level via signal_raise/signal_lower on the CONNECT node.
- Result: THERMAL_TRIP_OUT is asserted toward downstream hardware; a rising-edge HAP was posted for thermtrip_in observers. *Source: srv-pm/code/hwrs-gen2/attributes.dml, common/code/platform-common/unified-common-code/signals/signal-templates.dml*

2) FLOW: firmware-assert-trip
- Trigger: firmware writes/sets the thermal_trip pseudo attribute on dmr_imh_hwrs_fv.
- Steps:
  1. The thermal_trip pseudo attribute value is updated by the attribute write handler.
  2. Device attribute handler (attributes.dml) drives the THERMAL_TRIP_OUT CONNECT to match the firmware-requested state.
- Result: THERMAL_TRIP_OUT is driven to the firmware-requested state. The thermal_trip attribute represents a firmware-controlled thermal-trip condition and is not checkpointed. *Source: srv-pm/code/hwrs-gen2/attributes.dml*

Notes on arbitration and state:
- Both the input-forwarding path and the pseudo attribute path can drive THERMAL_TRIP_OUT. The DML overrides in attributes.dml implement the forwarding and the pseudo attribute handler; no additional arbitration logic is described in the available sources. Where both paths are active, the final driven state is determined by the device DML implementation order and handlers — consult the attributes.dml code to determine precedence. *Source: srv-pm/code/hwrs-gen2/attributes.dml*

---

## Interface Signals

| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| thermtrip_in | PORT (IN) | signal_input | Upstream asserts/deasserts THERMTRIP# (thermtrip_in.signal_raise()/signal_lower()) | template records boolean level, enforces unique-edge transitions, posts HAP events (rising/falling/any); device overrides perform inverted forwarding into device logic which may drive THERMAL_TRIP_OUT. *Source: common/.../signal-templates.dml, srv-pm/.../attributes.dml* |
| THERMAL_TRIP_OUT | CONNECT (OUT) | discrete CONNECT node | Driven by device logic: either the inverted thermtrip_in path (attributes.dml) or firmware via thermal_trip pseudo attribute | Represents asserted/deasserted thermal-trip toward downstream hardware; raised/lowered by device calling signal_raise/signal_lower on the CONNECT. *Source: srv-pm/.../attributes.dml* |

(Port = IN to device; Connect = OUT from device)

---

## Behavioral Specification (for Software Feature Validators)

Each statement below is a precise, testable WHEN -> THEN assertion about observable model behavior.

- WHEN an upstream component invokes thermtrip_in.signal_raise() -> THEN the signal_input template records the asserted level and posts a rising-edge HAP notification; device logic performs inverted forwarding and THERMAL_TRIP_OUT is driven asserted toward downstream components.
  - Observable: HAP callback invoked for rising edge; THERMAL_TRIP_OUT CONNECT state is asserted. *Source: common/.../signal-templates.dml; srv-pm/.../attributes.dml*

- WHEN an upstream component invokes thermtrip_in.signal_lower() -> THEN the signal_input template posts a falling-edge HAP and device logic forwards the inverted deassertion to drive THERMAL_TRIP_OUT deasserted.
  - Observable: HAP callback invoked for falling edge; THERMAL_TRIP_OUT CONNECT state is deasserted. *Source: common/.../signal-templates.dml; srv-pm/.../attributes.dml*

- WHEN firmware sets the thermal_trip pseudo attribute to asserted -> THEN the device attribute handler drives THERMAL_TRIP_OUT asserted regardless of thermtrip_in level (device DML determines precedence).
  - Observable: THERMAL_TRIP_OUT CONNECT is asserted; thermal_trip attribute reads back asserted. Note: thermal_trip is pseudo (not checkpointed). *Source: srv-pm/.../attributes.dml*

- WHEN the same edge transition is requested twice (e.g., two consecutive signal_raise() calls without an intervening signal_lower()) -> THEN the signal_input template logs a specification-violation for a duplicate edge and does not re-post the same edge (duplicate behavior depends on template but is flagged).
  - Observable: a log entry indicating duplicate-edge attempt; (depending on template) duplicate HAP may not be posted. *Source: common/.../signal-templates.dml*

- WHEN a checkpoint/restore cycle occurs and thermal_trip was asserted only via the pseudo attribute -> THEN thermal_trip will not be restored to the asserted state after restore (the attribute is configured as "pseudo" and excluded from checkpoint/restore).
  - Observable: after restore, thermal_trip pseudo attribute is in its DML initial state (not preserved) and THERMAL_TRIP_OUT will reflect device initialization + any live inputs. *Source: srv-pm/.../attributes.dml*

---

## Test Case Scenarios (for Software Feature Validators)

| Scenario | Setup | Action | Expected Result | Verification Point |
|----------|-------|--------|-----------------|--------------------|
| External assert drives output | Boot simulation with dmr_imh_hwrs_fv present and downstream listener attached to THERMAL_TRIP_OUT | Call thermtrip_in.signal_raise() on the device port | THERMAL_TRIP_OUT is asserted toward downstream device; thermtrip_in rising-edge HAP delivered | Query CONNECT state for THERMAL_TRIP_OUT (asserted) and verify HAP observer callback executed |
| External deassert drives output | As above, after previous assert | Call thermtrip_in.signal_lower() | THERMAL_TRIP_OUT is deasserted; thermtrip_in falling-edge HAP delivered | CONNECT state is deasserted; HAP callback executed for falling edge |
| Firmware back-door assert | Simulation running; ensure no external thermtrip_in assertion | Write/SET device attribute thermal_trip = true (via Simics attribute write) | THERMAL_TRIP_OUT becomes asserted; attribute readback returns true | Read thermal_trip attribute; query THERMAL_TRIP_OUT CONNECT state (asserted) |
| Conflict / precedence observation | thermtrip_in asserted and firmware toggles thermal_trip | 1) Call thermtrip_in.signal_raise() 2) Write thermal_trip = false | Final THERMAL_TRIP_OUT state follows the device logic order (verify actual behavior) | Observe THERMAL_TRIP_OUT CONNECT state after each action and inspect attributes.dml code to confirm precedence |
| Checkpoint behavior of pseudo attribute | Set thermal_trip = true, create a checkpoint, then restore checkpoint | After restore, check thermal_trip and THERMAL_TRIP_OUT | thermal_trip is not preserved across restore; THERMAL_TRIP_OUT reflects live inputs or default state | Read thermal_trip attribute after restore (should not be true unless reasserted); verify THERMAL_TRIP_OUT state |

Notes for validators:
- Register reads/writes are not part of this capability (no registers are defined for thermal_trip in provided DML).
- HAP observation: validators should register for the thermtrip_in rising/falling HAPs via the Simics HAP mechanism to verify that edge events are posted.
- To inspect CONNECT state, use whatever simulator introspection API is available to query the connected node’s state (the exact API depends on the Simics test harness).

---

## Implementation Notes (for Simics Device Model Developers)

- Key DML source files:
  - srv-pm/code/hwrs-gen2/attributes.dml — contains device-specific attribute handlers and the overrides that forward thermtrip_in changes into THERMAL_TRIP_OUT. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
  - common/code/platform-common/unified-common-code/signals/signal-templates.dml — provides the signal_input template used for thermtrip_in, including level storage, unique-edge enforcement, and HAP posting. *Source: common/code/platform-common/unified-common-code/signals/signal-templates.dml*
  - dmr_imh_hwrs_fv device DML — declares ports, CONNECT nodes, and the thermal_trip pseudo attribute. *Source: device DML: dmr_imh_hwrs_fv*

- Template dependencies and inheritance:
  - thermtrip_in inherits behavior from the signal_input template. The template guarantees:
    - methods: signal_raise(), signal_lower()
    - HAP posting on edges
    - duplicate-edge detection/logging
  - The template should not be reimplemented; extend or override only via device-level observers or DML attribute handlers.

- Extension / override points:
  - attributes.dml is the intended extension point to:
    - change how thermtrip_in events are forwarded to THERMAL_TRIP_OUT (modify inversion, add guards, change precedence with the pseudo attribute).
    - add logging, additional HAPs, or additional side-effects (e.g., tracing counters).
  - If additional arbitration is required between firmware and external input, implement arbitration logic in attributes.dml (for example, priority bits, time windows, or explicit lock attributes).
  - To change checkpoint behavior of the firmware back-door, change the configuration of thermal_trip attribute (remove "pseudo" to include in checkpoint) — be aware of platform-level implications.

- Known simulation fidelity notes and caveats:
  - The thermal_trip pseudo attribute is explicitly non-checkpointed (configuration = "pseudo"): it is a back-door injection handle and state is not restored by checkpoint/restore operations. This differs from a hardware latched state that would be preserved across a system snapshot. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
  - No register-level model or FSM is provided for this capability in the available DML fragments; any register interactions expected on real hardware are not modeled here.
  - Both the input-forwarding code and the pseudo-attribute handler can drive THERMAL_TRIP_OUT. There is no separate hardware arbitration visible in the DML; implementers should be explicit in attributes.dml about intended precedence. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
  - The signal_input template enforces unique-edge transitions and logs duplicate-edge attempts; tests should expect logging of such violations and not treat duplicate edge calls as silently idempotent. *Source: common/.../signal-templates.dml*

---

## Platform Integration Notes (for Platform Architects)

- Role in the system:
  - dmr_imh_hwrs_fv provides a thermal-trip forwarding and firmware-controlled assertion capability that signals overtemperature conditions to downstream controllers. It acts as a gate/translator between an upstream THERMTRIP# source and downstream thermal-trip consumers, while also exposing firmware back-door control for diagnostics or forced behavior.

- Required connections:
  - thermtrip_in (PORT) must be connected to the upstream thermal-sensor/controller that asserts the physical THERMTRIP# line.
  - THERMAL_TRIP_OUT (CONNECT) must be connected to downstream consumers that react to an asserted thermal-trip (power management controllers, PMICs, system controllers).
  - If the platform design allows both external hardware and firmware to drive the downstream trip line, architects must consider electrical/functional arbitration semantics; in Simics both paths write the CONNECT — real hardware may have diode-or, open-drain with pull-ups, or dedicated arbitration logic not modeled here. *Source: srv-pm/code/hwrs-gen2/attributes.dml*

- Dependencies:
  - The capability depends on the signal template infrastructure (signal_input) and the HAP/event system for edge notifications. Ensure the platform includes these common signal templates and that HAP observers are in place for components that need to react to edges. *Source: common/code/platform-common/unified-common-code/signals/signal-templates.dml*
  - Firmware test flows that use the thermal_trip pseudo attribute will require test harness access to device-level attributes in the simulator (the platform must permit attribute writes to device objects).

- Configuration parameters:
  - thermal_trip attribute is configured as "pseudo" (non-checkpointed). If platform behavior requires persistence of the firmware-controlled trip through snapshot/restore, change this configuration in the device DML — but be aware this is a behavioral change relative to the current model. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
  - No timing/configuration knobs (delays, hysteresis, timers) are present in the provided DML; if platform needs thermal hysteresis or delayed trip behavior, those must be added to attributes.dml or a new FSM.

---

If you need: exact DML fragments for the attributes.dml overrides, example unit tests (Simics Python) that exercise thermtrip_in and thermal_trip attribute, or a suggested attributes.dml patch that implements explicit arbitration between firmware and hardware paths, I can provide those.